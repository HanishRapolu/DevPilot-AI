"""Bounded, sanitized working copies. No repository code runs on the host."""
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from uuid import uuid4

from app.mcp_tools.common import ToolError, exclusive, repository_name

MAX_FILE = 256 * 1024
MAX_PATCH = 64 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_FILES = 500
BLOCKED_DIRS = {"node_modules", "venv", "env", "__pycache__", "dist", "build", "credentials", "secrets"}
EXTENSIONS = {".py", ".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".ini", ".cfg"}


def safe_name(name: str) -> str:
    if not name or len(name) > 240 or "\\" in name or ":" in name or "\x00" in name:
        raise ToolError("Invalid repository path.")
    parts = name.split("/")
    if any(not p or p in (".", "..") or p.startswith(".") or p.endswith((" ", ".")) for p in parts):
        raise ToolError("Hidden files and path traversal are forbidden.")
    if any(p.lower() in BLOCKED_DIRS for p in parts):
        raise ToolError("Protected directory.")
    for part in parts:
        if not re.fullmatch(r"[A-Za-z0-9_ .-]+", part):
            raise ToolError("Unsupported path characters.")
        if part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}:
            raise ToolError("Reserved filename.")
    lower = parts[-1].lower()
    if any(word in lower for word in ("credential", "secret", "token", "password", "id_rsa", "id_ed25519")):
        raise ToolError("Credential-related files are forbidden.")
    if PurePosixPath(name).suffix.lower() not in EXTENSIONS:
        raise ToolError("File type is not allowed.")
    return name


def checked_path(root: Path, name: str) -> Path:
    safe_name(name)
    current = root
    for part in name.split("/"):
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ToolError("Symlinks and junctions are forbidden.")
    if not current.resolve().is_relative_to(root.resolve()):
        raise ToolError("Path escapes the workspace.")
    if not current.is_file() or current.stat().st_nlink > 1:
        raise ToolError("Only existing regular files with no hard links are allowed.")
    return current


def read_text(root: Path, name: str) -> str:
    path = checked_path(root, name)
    with path.open("rb") as handle:
        raw = handle.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE or b"\x00" in raw:
        raise ToolError("File exceeds size limit or is binary.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ToolError("Only UTF-8 text files are supported.") from None


class Workspace:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.manifest = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
        self.root = self.directory / "repo"
        self.baseline = self.directory / "baseline"
        self.files = self.manifest["files"]
        self.allowed = frozenset(self.manifest["authorized_files"])
        for name in self.files:
            safe_name(name)
        if any(path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
               for path in (self.root, self.baseline)):
            raise ToolError("Invalid workspace roots.")

    @classmethod
    def from_environment(cls):
        value = os.environ.get("DEVPILOT_WORKSPACE")
        if not value:
            raise ToolError("Prepare a workspace and configure MCP_WORKSPACE.")
        return cls(Path(value))

    @classmethod
    def create(cls, source: Path, state: Path, repository: str, authorized_files: list[str], demo=False):
        source, state = source.resolve(), state.resolve()
        repository = repository_name(repository)
        if state.is_relative_to(source):
            raise ToolError("State directory must be outside the source checkout.")
        for name in authorized_files:
            safe_name(name)
        modes = {}
        if demo:
            names = ["calculator.py", "test_calculator.py", "pytest.ini", "README.md"]
            revision = None
            content = {name: read_text(source, name) for name in names}
            modes = {name: "100644" for name in names}
        else:
            def git(*args):
                command = ["git", "--no-pager", "--no-replace-objects", "-c", "core.fsmonitor=false",
                           "-c", "core.hooksPath=", "-C", str(source), *args]
                done = subprocess.run(command, capture_output=True, timeout=15, check=False)
                if done.returncode:
                    raise ToolError("Unable to read the source Git checkout.")
                return done.stdout
            origin = git("remote", "get-url", "origin").decode().strip().removesuffix(".git").lower()
            if origin not in (f"https://github.com/{repository}", f"git@github.com:{repository}"):
                raise ToolError("Source origin must match the authorized GitHub repository.")
            revision = git("rev-parse", "HEAD").decode().strip()
            if not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise ToolError("Unsupported Git revision.")
            # Read committed objects only. Even `git status` can invoke configured
            # clean filters, so do not run it against a task repository on the host.
            content = {}
            for entry in git("ls-tree", "-rz", "--full-tree", revision).split(b"\x00"):
                if not entry:
                    continue
                meta, raw_name = entry.split(b"\t", 1)
                mode, kind, oid = meta.decode().split()
                name = raw_name.decode("utf-8")
                try:
                    safe_name(name)
                except ToolError:
                    continue
                if mode not in ("100644", "100755") or kind != "blob":
                    continue
                # Source links are rejected, even though bytes come from the Git object.
                checked_path(source, name)
                size = int(git("cat-file", "-s", oid.decode() if isinstance(oid, bytes) else oid))
                if size > MAX_FILE:
                    continue
                raw = git("cat-file", "blob", oid)
                if b"\x00" in raw:
                    continue
                try:
                    content[name] = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                modes[name] = mode
                if len(content) > MAX_FILES or sum(len(v.encode()) for v in content.values()) > MAX_TOTAL:
                    raise ToolError("Repository exceeds MVP workspace limits.")
        if not authorized_files or not set(authorized_files).issubset(content):
            raise ToolError("Authorized files must be present, safe, tracked text files.")
        directory = state / "workspaces" / str(uuid4())
        directory.mkdir(parents=True, mode=0o700)
        for folder in ("repo", "baseline"):
            for name, text in content.items():
                path = directory / folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(text.encode("utf-8"))
        manifest = {"repository": repository, "revision": revision, "files": sorted(content),
                    "authorized_files": sorted(set(authorized_files)), "modes": modes}
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return cls(directory)

    def lock(self):
        return exclusive(self.directory / "workspace.lock")

    def read(self, name: str) -> str:
        safe_name(name)
        if name not in self.files:
            raise ToolError("File is not part of this workspace.")
        return read_text(self.root, name)

    def snapshot(self) -> dict[str, str]:
        values = {name: self.read(name) for name in self.files}
        if sum(len(v.encode()) for v in values.values()) > MAX_TOTAL:
            raise ToolError("Workspace exceeds total size limit.")
        return values

    def changes(self) -> dict[str, str]:
        changes = {}
        for name, current in self.snapshot().items():
            if current != read_text(self.baseline, name):
                if name not in self.allowed:
                    raise ToolError("An unauthorized file has changed.")
                changes[name] = current
        return changes

    def diff(self) -> dict:
        changes = self.changes()
        patch = "".join("".join(difflib.unified_diff(
            read_text(self.baseline, name).splitlines(keepends=True), current.splitlines(keepends=True),
            fromfile=f"a/{name}", tofile=f"b/{name}")) for name, current in sorted(changes.items()))
        if len(patch.encode()) > MAX_PATCH:
            raise ToolError("Diff exceeds patch size limit.")
        return {"patch": patch, "sha256": hashlib.sha256(patch.encode()).hexdigest(), "files": sorted(changes)}
