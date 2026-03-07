"""
Formatter / pretty-printer for .sw (Swarm Language) files.

Re-indents consistently (4 spaces per nesting level), normalizes whitespace
(single blank line between top-level blocks, no trailing whitespace), and
preserves comments.

Usage:
    uv run swarm fmt program.sw             # prints to stdout
    uv run swarm fmt program.sw --in-place   # overwrites file
"""

import re
import sys
from pathlib import Path

INDENT = "    "

OPEN_BRACE = re.compile(r"\{[ \t]*(?://.*)?$")
CLOSE_BRACE = re.compile(r"^\s*\}")
BLOCK_COMMENT_START = re.compile(r"/\*")
BLOCK_COMMENT_END = re.compile(r"\*/")

TOP_KEYWORDS = {"state", "behavior", "init", "func", "const", "register", "tag"}
TOP_BLOCK_KEYWORDS = {"state", "behavior", "init", "func"}
TOP_DECL_KEYWORDS = {"const", "register", "tag"}


def _top_keyword(stripped: str) -> str | None:
    first = stripped.split()[0] if stripped.split() else ""
    return first if first in TOP_KEYWORDS else None


def _is_top_level_start(stripped: str) -> bool:
    return _top_keyword(stripped) is not None


def _is_comment_only(stripped: str) -> bool:
    return stripped.startswith("//") or stripped.startswith("/*")


def _is_section_divider(stripped: str) -> bool:
    return stripped.startswith("//") and len(stripped) > 10 and stripped.count("-") >= 5


def _count_braces(line: str) -> tuple[int, int]:
    """Count { and } in a line, ignoring those inside // comments and strings."""
    opens = 0
    closes = 0
    in_string = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch == '/' and i + 1 < len(line) and line[i + 1] == '/':
                break
            if ch == '{':
                opens += 1
            elif ch == '}':
                closes += 1
        i += 1
    return opens, closes


def format_sw(src: str) -> str:
    raw_lines = src.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines = raw_lines[:-1]

    result: list[str] = []
    depth = 0
    in_block_comment = False
    in_register_paren = False
    prev_was_blank = False
    prev_top_kw: str | None = None

    for raw in raw_lines:
        stripped = raw.strip()

        if in_block_comment:
            result.append(INDENT * depth + stripped if stripped else "")
            if BLOCK_COMMENT_END.search(stripped):
                in_block_comment = False
            prev_was_blank = False
            continue

        if not stripped:
            if not prev_was_blank:
                result.append("")
                prev_was_blank = True
            continue

        if BLOCK_COMMENT_START.search(stripped) and not BLOCK_COMMENT_END.search(stripped):
            in_block_comment = True

        opens, closes = _count_braces(stripped)

        # Track register (...) paren blocks
        if re.match(r'register\s*\(', stripped) and ')' not in stripped:
            in_register_paren = True
            opens += 1
        elif in_register_paren and stripped.startswith(')'):
            in_register_paren = False
            closes += 1

        leading_closes = 0
        for ch in stripped:
            if ch == '}':
                leading_closes += 1
            elif ch == ')' and not in_register_paren:
                leading_closes += 1
            elif ch not in ' \t':
                break

        indent_depth = max(depth - leading_closes, 0)

        # Insert blank line before top-level blocks and section dividers
        if indent_depth == 0 and result:
            cur_kw = _top_keyword(stripped)
            is_divider = _is_section_divider(stripped)

            # Always blank before block keywords (state, behavior, init, func)
            # and section dividers. For declaration keywords (const, register, tag),
            # only blank when transitioning from a different keyword type.
            needs_blank = False
            if is_divider:
                needs_blank = True
            elif cur_kw in TOP_BLOCK_KEYWORDS:
                needs_blank = True
            elif cur_kw in TOP_DECL_KEYWORDS:
                needs_blank = prev_top_kw is not None and prev_top_kw != cur_kw

            if needs_blank and not prev_was_blank:
                result.append("")

        line = INDENT * indent_depth + stripped

        result.append(line)
        prev_was_blank = False

        # Track top-level keyword for grouping decisions
        if indent_depth == 0:
            kw = _top_keyword(stripped)
            if kw:
                prev_top_kw = kw
            elif _is_section_divider(stripped) or _is_comment_only(stripped):
                pass  # comments don't reset the keyword tracker
            elif stripped.startswith("}"):
                prev_top_kw = None

        # Update depth for subsequent lines
        depth = max(depth - closes + opens, 0)

    while result and result[-1] == "":
        result.pop()

    result = [line.rstrip() for line in result]

    return "\n".join(result) + "\n"


def main():
    if len(sys.argv) < 2:
        print("Usage: swarm fmt <file.sw> [--in-place]", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    in_place = "--in-place" in sys.argv

    src = path.read_text()
    formatted = format_sw(src)

    if in_place:
        path.write_text(formatted)
        print(f"Formatted {path}", file=sys.stderr)
    else:
        sys.stdout.write(formatted)


if __name__ == "__main__":
    main()
