"""Internal repository implementation; its public agent interface is MCP."""
import re

from app.mcp_tools.common import ToolError
from app.mcp_tools.workspace import MAX_FILE, MAX_PATCH, Workspace, checked_path, safe_name


def parse_patch(patch: str, workspace: Workspace) -> dict[str, str]:
    """Strict unified diffs: existing UTF-8 files only; no renames, modes or binary data."""
    if not patch or len(patch.encode()) > MAX_PATCH or not patch.endswith("\n"):
        raise ToolError("Patch must be a newline-terminated unified diff within 64 KiB.")
    lines = patch.splitlines(keepends=True)
    updates = {}
    index = 0
    while index < len(lines):
        if lines[index].startswith("diff --git "):
            # Optional metadata is accepted only with identical safe paths.
            metadata = lines[index].rstrip("\n").split(" ")
            if len(metadata) != 4 or metadata[2][2:] != metadata[3][2:]:
                raise ToolError("Invalid diff metadata.")
            index += 1
            if index < len(lines) and lines[index].startswith("index "):
                if not re.fullmatch(r"index [0-9a-f]+\.\.[0-9a-f]+(?: 100(?:644|755))?\n", lines[index]):
                    raise ToolError("Unsupported diff metadata.")
                index += 1
        if index + 1 >= len(lines) or not lines[index].startswith("--- a/") or not lines[index + 1].startswith("+++ b/"):
            raise ToolError("Only unified patches for existing files are allowed.")
        name = lines[index][6:].rstrip("\n")
        safe_name(name)
        if lines[index + 1][6:].rstrip("\n") != name or name in updates or name not in workspace.allowed:
            raise ToolError("Patch target is not authorized or is duplicated.")
        original = workspace.read(name).splitlines(keepends=True)
        output = []
        cursor = 0
        index += 2
        hunks = 0
        while index < len(lines) and lines[index].startswith("@@ "):
            match = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n", lines[index])
            if not match:
                raise ToolError("Invalid hunk header.")
            old_start, old_count, new_start, new_count = match.groups()
            old_count = int(old_count) if old_count is not None else 1
            new_count = int(new_count) if new_count is not None else 1
            position = int(old_start) - (1 if old_count else 0)
            if position < cursor or position > len(original):
                raise ToolError("Overlapping or out-of-range patch hunk.")
            output.extend(original[cursor:position])
            if int(new_start) - (1 if new_count else 0) != len(output):
                raise ToolError("Incorrect new-file hunk position.")
            cursor = position
            index += 1
            removed = added = 0
            while removed < old_count or added < new_count:
                if index >= len(lines) or lines[index][:1] not in (" ", "-", "+"):
                    raise ToolError("Truncated patch hunk.")
                prefix, value = lines[index][0], lines[index][1:]
                if prefix in (" ", "-"):
                    if cursor >= len(original) or original[cursor] != value:
                        raise ToolError("Patch context does not match the current file.")
                    cursor += 1
                    removed += 1
                if prefix in (" ", "+"):
                    output.append(value)
                    added += 1
                if removed > old_count or added > new_count:
                    raise ToolError("Patch hunk counts do not match.")
                index += 1
            hunks += 1
        if not hunks:
            raise ToolError("Patch contains no hunks.")
        output.extend(original[cursor:])
        text = "".join(output)
        if len(text.encode()) > MAX_FILE or "\x00" in text:
            raise ToolError("Patched file exceeds limit or contains binary data.")
        updates[name] = text
    return updates


class RepositoryTools:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def list_files(self) -> dict:
        with self.workspace.lock():
            return {"files": [{"path": name, "bytes": len(text.encode()),
                               "editable": name in self.workspace.allowed}
                              for name, text in self.workspace.snapshot().items()]}

    def read_file(self, path: str) -> dict:
        with self.workspace.lock():
            return {"path": path, "content": self.workspace.read(path)}

    def search_code(self, query: str) -> dict:
        if not 1 <= len(query) <= 200:
            raise ToolError("Search query must contain 1–200 characters.")
        matches = []
        with self.workspace.lock():
            for name, text in self.workspace.snapshot().items():
                for line, content in enumerate(text.splitlines(), 1):
                    if query in content:
                        matches.append({"path": name, "line": line, "text": content[:1000]})
                        if len(matches) >= 100:
                            return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": False}

    def apply_patch(self, patch: str) -> dict:
        with self.workspace.lock():
            self.workspace.changes()  # Refuse a workspace already modified outside policy.
            updates = parse_patch(patch, self.workspace)
            before = {name: self.workspace.read(name) for name in updates}
            try:
                for name, text in updates.items():
                    checked_path(self.workspace.root, name).write_bytes(text.encode())
                diff = self.workspace.diff()  # Also bound the cumulative patch.
            except Exception:
                for name, text in before.items():
                    checked_path(self.workspace.root, name).write_bytes(text.encode())
                raise
            return {"changed_files": sorted(updates), "diff_sha256": diff["sha256"]}

    def get_diff(self) -> dict:
        with self.workspace.lock():
            return self.workspace.diff()
