import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
import time
import threading
from uuid import uuid4

from app.mcp_tools.common import ToolError
from app.mcp_tools.workspace import Workspace


def bounded_run(command, *, input, timeout, **kwargs):
    """Drain output continuously, retaining at most 128 KiB per stream."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    captured = [bytearray(), bytearray()]

    def drain(stream, target):
        try:
            while chunk := stream.read(8192):
                remaining = 128 * 1024 - len(target)
                if remaining > 0:
                    target.extend(chunk[:remaining])
        finally:
            stream.close()

    def feed():
        try:
            process.stdin.write(input)
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()

    threads = [threading.Thread(target=drain, args=(process.stdout, captured[0]), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, captured[1]), daemon=True),
               threading.Thread(target=feed, daemon=True)]
    for thread in threads:
        thread.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise
    finally:
        for thread in threads:
            thread.join(timeout=1)
    return subprocess.CompletedProcess(command, process.returncode, bytes(captured[0]), bytes(captured[1]))


class TestingTools:
    def __init__(self, workspace: Workspace, image="devpilot-python-tests:phase2", timeout=60, runner=None):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._/:@-]{0,200}", image):
            raise ToolError("Invalid sandbox image.")
        if not 5 <= timeout <= 120:
            raise ToolError("Sandbox timeout must be between 5 and 120 seconds.")
        self.workspace = workspace
        self.image = image
        self.timeout = timeout
        self.runner = runner

    @classmethod
    def from_environment(cls):
        return cls(Workspace.from_environment(), os.getenv("SANDBOX_IMAGE", "devpilot-python-tests:phase2"),
                   int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "60")))

    def run(self, operation: str) -> dict:
        if operation not in ("run_tests", "check_syntax"):
            raise ToolError("Unsupported testing operation.")
        with self.workspace.lock():
            files = self.workspace.snapshot()
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w") as tar:
                for name, text in files.items():
                    encoded = text.encode()
                    info = tarfile.TarInfo(name)
                    info.size, info.mode, info.uid, info.gid = len(encoded), 0o644, 65534, 65534
                    tar.addfile(info, io.BytesIO(encoded))
            digest = hashlib.sha256(archive.getvalue()).hexdigest()
            name = "devpilot-test-" + uuid4().hex
            command = ["docker", "run", "--rm", "--pull=never", "--name", name,
                       "--network=none", "--read-only", "--user=65534:65534",
                       "--cap-drop=ALL", "--security-opt=no-new-privileges",
                       "--pids-limit=64", "--memory=256m", "--memory-swap=256m", "--cpus=1",
                       "--log-driver=none", "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
                       "--tmpfs=/workspace:rw,noexec,nosuid,size=16m,mode=1777",
                       "--env=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", "--env=PYTHONDONTWRITEBYTECODE=1",
                       "--interactive", self.image, operation, str(self.timeout)]
            started = time.monotonic()
            cleanup_ok = True
            try:
                completed = (self.runner or bounded_run)(command, input=archive.getvalue(), capture_output=True,
                                        timeout=self.timeout + 10, check=False)
                # Container output is untrusted, even though its runner is fixed.
                raw = completed.stdout[:128 * 1024].decode("utf-8", errors="replace")
                if completed.returncode in (125, 126, 127):
                    report = {"status": "infrastructure_error", "exit_code": completed.returncode,
                              "output": "Docker unavailable or sandbox image missing. Build the documented image locally."}
                else:
                    try:
                        payload = json.loads(raw)
                        report = {"status": "passed" if completed.returncode == 0 else "failed",
                                  "exit_code": completed.returncode, "output": str(payload["output"])[:12000]}
                        if payload.get("status") == "timeout":
                            report["status"] = "timeout"
                    except (ValueError, KeyError, TypeError):
                        report = {"status": "failed", "exit_code": completed.returncode,
                                  "output": "Invalid or missing sandbox result."}
            except subprocess.TimeoutExpired:
                report = {"status": "timeout", "exit_code": None, "output": "Sandbox execution exceeded its deadline."}
            except OSError:
                report = {"status": "infrastructure_error", "exit_code": None, "output": "Docker CLI could not be started."}
            finally:
                try:
                    # Killing docker's client alone does not stop a container.
                    cleanup = (self.runner or subprocess.run)(["docker", "rm", "-f", name], capture_output=True, timeout=10, check=False)
                    if cleanup.returncode != 0 and b"No such container" not in cleanup.stderr:
                        cleanup_ok = False
                except (OSError, subprocess.TimeoutExpired):
                    cleanup_ok = False
            report.update(duration_seconds=round(time.monotonic() - started, 3), operation=operation,
                          snapshot_sha256=digest, output_untrusted=True, cleanup_confirmed=cleanup_ok)
            if not cleanup_ok:
                report["container_name"] = name
            (self.workspace.directory / f"{operation}.json").write_text(json.dumps(report), encoding="utf-8")
            return report

    def run_tests(self) -> dict:
        return self.run("run_tests")

    def check_syntax(self) -> dict:
        return self.run("check_syntax")

    def get_test_results(self) -> dict:
        with self.workspace.lock():
            path = self.workspace.directory / "run_tests.json"
            if not path.exists():
                return {"status": "not_run", "exit_code": None, "duration_seconds": 0, "output": ""}
            return json.loads(path.read_text(encoding="utf-8"))
