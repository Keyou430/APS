"""Text processing tools — regex, JSON/YAML/XML parsing, diff."""

from __future__ import annotations

import difflib
import json
import logging
import re

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

HAS_XML = False  # xml.etree.ElementTree is stdlib, always available


def register_text_tools(mcp: FastMCP) -> None:
    """Register text processing tools."""

    @mcp.tool(
        name="regex_match",
        description="""Match text against a regular expression pattern. Returns all matches.

Uses Python regex syntax (re module). Capture groups are supported.""",
    )
    async def regex_match(
        text: str,
        pattern: str,
        flags: str = "",
        group: int | None = None,
    ) -> str:
        """Apply regex matching to text.

        Args:
            text: The text to search
            pattern: Regular expression pattern (Python syntax)
            flags: Comma-separated flags: 'ignorecase', 'multiline', 'dotall'
            group: If specified, return only this capture group from each match
        """
        try:
            flag_map = {
                "ignorecase": re.IGNORECASE,
                "multiline": re.MULTILINE,
                "dotall": re.DOTALL,
            }
            flag_value = 0
            for f in flags.split(","):
                f = f.strip().lower()
                if f in flag_map:
                    flag_value |= flag_map[f]

            regex = re.compile(pattern, flag_value)
            matches = regex.finditer(text)

            results = []
            for i, m in enumerate(matches, 1):
                if group is not None and m.lastindex is not None and group <= m.lastindex:
                    results.append(f"Match {i}: {m.group(group)}")
                elif m.groups():
                    results.append(f"Match {i}: {m.group(0)}")
                    for j, g in enumerate(m.groups(), 1):
                        if g is not None:
                            results.append(f"  Group {j}: {g}")
                else:
                    results.append(f"Match {i}: {m.group(0)}")

            if not results:
                return f"No matches found for pattern '{pattern}'"

            return "\n".join(results)

        except re.error as exc:
            return f"❌ Invalid regex pattern: {exc}"
        except Exception as exc:
            return f"❌ Error: {exc}"

    @mcp.tool(
        name="json_parse",
        description="""Parse and pretty-print JSON content. Validates JSON structure and formats it
for readability. Returns error details if the JSON is invalid.""",
    )
    async def json_parse(text: str, indent: int = 2) -> str:
        """Parse and format JSON.

        Args:
            text: JSON string to parse
            indent: Indentation spaces for output (default: 2)
        """
        try:
            data = json.loads(text)
            formatted = json.dumps(data, indent=indent, ensure_ascii=False)
            return formatted
        except json.JSONDecodeError as exc:
            # Show context around the error
            lines = text.split("\n")
            error_line = exc.lineno - 1
            context_start = max(0, error_line - 2)
            context_end = min(len(lines), error_line + 3)
            context = []
            for i in range(context_start, context_end):
                marker = "→" if i == error_line else " "
                context.append(f"{marker} L{i + 1}: {lines[i]}")
            return (
                f"❌ Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}\n\n"
                + "\n".join(context)
            )

    @mcp.tool(
        name="yaml_parse",
        description="""Parse and convert YAML to JSON. Validates YAML structure and returns
the equivalent JSON representation.""",
    )
    async def yaml_parse(text: str) -> str:
        """Parse YAML and return as JSON.

        Args:
            text: YAML string to parse
        """
        if not HAS_YAML:
            return "❌ PyYAML is not installed. Install with: pip install pyyaml"

        try:
            data = yaml.safe_load(text)
            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            return formatted
        except yaml.YAMLError as exc:
            return f"❌ Invalid YAML: {exc}"
        except Exception as exc:
            return f"❌ Error: {exc}"

    @mcp.tool(
        name="diff_text",
        description="""Compare two texts and show differences (unified diff format).

Returns a line-by-line diff with context. Lines starting with '-' were removed,
lines starting with '+' were added, and lines starting with ' ' are unchanged context.""",
    )
    async def diff_text(
        text_a: str,
        text_b: str,
        label_a: str = "original",
        label_b: str = "modified",
        context_lines: int = 3,
    ) -> str:
        """Generate a unified diff between two texts.

        Args:
            text_a: Original text
            text_b: Modified text
            label_a: Label for the original text
            label_b: Label for the modified text
            context_lines: Number of context lines around each change
        """
        lines_a = text_a.splitlines(keepends=True)
        lines_b = text_b.splitlines(keepends=True)

        diff = difflib.unified_diff(
            lines_a, lines_b,
            fromfile=label_a, tofile=label_b,
            n=context_lines,
        )

        result = "".join(diff)
        if not result.strip():
            return "✅ No differences found — the texts are identical."
        return result
