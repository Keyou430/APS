"""File operation tools — read, write, glob, search files."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastmcp import FastMCP

from hermes_mcp.config.schema import HermesMCPConfig

logger = logging.getLogger(__name__)


def _is_allowed_path(path: str, allowed_dirs: list[str]) -> bool:
    """Check if a path is within allowed directories."""
    resolved = Path(path).resolve()
    for allowed in allowed_dirs:
        allowed_resolved = Path(allowed).resolve()
        try:
            resolved.relative_to(allowed_resolved)
            return True
        except ValueError:
            continue
    return False


def _is_allowed_extension(path: str, allowed_exts: list[str]) -> bool:
    """Check if a file has an allowed extension."""
    ext = Path(path).suffix.lower()
    if not ext:
        return True  # Files without extension are allowed
    return ext in allowed_exts


def register_file_tools(mcp: FastMCP, config: HermesMCPConfig) -> None:
    """Register file operation tools."""

    allowed_dirs = config.file_ops.allowed_directories
    max_size = config.file_ops.max_file_size
    allowed_exts = config.file_ops.allowed_extensions

    @mcp.tool(
        name="read_file",
        description="""Read the contents of a file. Returns the file content as text.

Only files within allowed directories and with allowed extensions can be read.
Maximum file size is enforced to prevent memory issues.""",
    )
    async def read_file(path: str, encoding: str = "utf-8") -> str:
        """Read a file from the filesystem.

        Args:
            path: Path to the file to read
            encoding: Text encoding (default: utf-8)
        """
        if not os.path.isfile(path):
            return f"❌ File not found: {path}"

        if not _is_allowed_path(path, allowed_dirs):
            return f"❌ Access denied: '{path}' is outside allowed directories"

        if not _is_allowed_extension(path, allowed_exts):
            return f"❌ Access denied: file extension not allowed for '{path}'"

        file_size = os.path.getsize(path)
        if file_size > max_size:
            return (
                f"❌ File too large: {file_size:,} bytes "
                f"(max {max_size:,} bytes)"
            )

        try:
            content = Path(path).read_text(encoding=encoding)
            if file_size > 50_000:
                return (
                    f"📄 {path} ({file_size:,} bytes) — showing first 50KB:\n\n"
                    + content[:50_000]
                    + "\n\n... [truncated]"
                )
            return content
        except UnicodeDecodeError:
            return f"❌ Cannot read '{path}' as text (binary file?) — try a different encoding"
        except Exception as exc:
            return f"❌ Error reading file: {exc}"

    @mcp.tool(
        name="write_file",
        description="""Write content to a file. Creates the file if it doesn't exist, overwrites if it does.

Only files within allowed directories can be written. This is a destructive operation
for existing files — use with caution.""",
    )
    async def write_file(path: str, content: str, encoding: str = "utf-8") -> str:
        """Write content to a file.

        Args:
            path: Path to the file to write
            content: Content to write
            encoding: Text encoding (default: utf-8)
        """
        if not _is_allowed_path(path, allowed_dirs):
            return f"❌ Access denied: '{path}' is outside allowed directories"

        if not _is_allowed_extension(path, allowed_exts):
            return f"❌ Access denied: file extension not allowed for '{path}'"

        try:
            # Ensure parent directory exists
            parent = Path(path).parent
            parent.mkdir(parents=True, exist_ok=True)

            Path(path).write_text(content, encoding=encoding)
            file_size = os.path.getsize(path)
            return f"✅ Written {file_size:,} bytes to {path}"
        except Exception as exc:
            return f"❌ Error writing file: {exc}"

    @mcp.tool(
        name="glob_files",
        description="""Find files matching a glob pattern. Returns relative file paths.

Supports standard glob patterns:
- **/*.py — all Python files recursively
- *.txt — all text files in current directory
- src/**/*.ts — all TypeScript files under src/""",
    )
    async def glob_files(pattern: str, directory: str = ".") -> str:
        """Find files matching a glob pattern.

        Args:
            pattern: Glob pattern to match (e.g., '**/*.py')
            directory: Root directory for the search
        """
        if not _is_allowed_path(directory, allowed_dirs):
            return f"❌ Access denied: '{directory}' is outside allowed directories"

        try:
            matches = sorted(Path(directory).glob(pattern))
            if not matches:
                return f"No files matching '{pattern}' in {directory}"

            lines = [f"Files matching '{pattern}' in {directory}:"]
            for m in matches[:200]:
                if m.is_file():
                    size = m.stat().st_size
                    lines.append(f"  {m} ({size:,} bytes)")

            if len(matches) > 200:
                lines.append(f"  ... and {len(matches) - 200} more files")

            return "\n".join(lines)
        except Exception as exc:
            return f"❌ Error during glob: {exc}"

    @mcp.tool(
        name="search_files",
        description="""Search for files whose names contain the given string (case-insensitive).

Useful for finding files when you know part of the name but not the exact path.""",
    )
    async def search_files(query: str, directory: str = ".") -> str:
        """Search for files by name substring.

        Args:
            query: Substring to search for in file names
            directory: Root directory for the search
        """
        if not _is_allowed_path(directory, allowed_dirs):
            return f"❌ Access denied: '{directory}' is outside allowed directories"

        try:
            matches = []
            for root, dirs, files in os.walk(directory):
                # Skip hidden directories
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    if query.lower() in f.lower():
                        full_path = Path(root) / f
                        matches.append(full_path)

            if not matches:
                return f"No files matching '{query}' in {directory}"

            matches.sort()
            lines = [f"Files matching '{query}' in {directory}:"]
            for m in matches[:100]:
                size = m.stat().st_size
                lines.append(f"  {m} ({size:,} bytes)")

            if len(matches) > 100:
                lines.append(f"  ... and {len(matches) - 100} more files")

            return "\n".join(lines)
        except Exception as exc:
            return f"❌ Error during search: {exc}"
