"""Trusted runner baked into the image; never copied from a task checkout."""
import ast
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile


def main():
    operation, timeout = sys.argv[1], min(int(sys.argv[2]), 120)
    if operation not in ("run_tests", "check_syntax"):
        raise ValueError("Unsupported operation")
    raw = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError("Archive too large")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        members = archive.getmembers()
        if len(members) > 500:
            raise ValueError("Too many files")
        for member in members:
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or any(p in (".", "..") or p.startswith(".") for p in path.parts)
                    or "\\" in member.name or ":" in member.name or member.size > 256 * 1024):
                raise ValueError("Unsafe archive member")
            target = Path("/workspace") / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source:
                target.write_bytes(source.read())
    if operation == "check_syntax":
        failures = []
        for path in Path("/workspace").rglob("*.py"):
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path.relative_to("/workspace")))
            except (SyntaxError, UnicodeError) as exc:
                failures.append(f"{path.relative_to('/workspace')}: {type(exc).__name__}")
        print(json.dumps({"status": "failed" if failures else "passed", "output": "\n".join(failures) or "Python syntax is valid."}))
        return int(bool(failures))
    command = [sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", "/opt/pytest.ini", "--rootdir=/workspace", "/workspace"]
    with tempfile.TemporaryFile() as output:
        try:
            done = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, timeout=timeout,
                                  env={"PATH": os.environ["PATH"], "HOME": "/tmp", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                                       "PYTHONDONTWRITEBYTECODE": "1"}, check=False)
            status, code = "passed" if done.returncode == 0 else "failed", done.returncode
        except subprocess.TimeoutExpired:
            status, code = "timeout", 124
        output.seek(0)
        text = output.read(12000).decode("utf-8", errors="replace")
    print(json.dumps({"status": status, "output": text}))
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print(json.dumps({"status": "failed", "output": "Sandbox runner rejected input or failed."}))
        raise SystemExit(2)
