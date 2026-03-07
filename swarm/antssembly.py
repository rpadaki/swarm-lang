"""
Antssembly Compiler / Composer / Static Analyzer

Features:
- #include "snippets/file.ant" to inline snippet files
- #define NAME VALUE for text substitution
- #ifdef / #ifndef / #endif for conditional compilation
- Static analysis: label cross-refs, op counts, register usage
- Outputs flat .ant file ready to paste

Usage:
    swarm antssembly programs/v3.ant --analyze   # analyze only
    swarm antssembly programs/v3.ant --strip     # strip debug symbols
    swarm antssembly programs/v3.ant             # print to stdout
"""

import sys
import re
from pathlib import Path

LIB_DIR = Path(__file__).parent.parent / "lib"

ACTIONS = {"MOVE", "PICKUP", "DROP"}
BRANCH_OPS = {"JMP", "JEQ", "JNE", "JGT", "JLT", "CALL"}
SENSE_OPS = {"SENSE", "SMELL", "SNIFF", "PROBE", "CARRYING", "ID"}
ARITH_OPS = {"SET", "ADD", "SUB", "MOD", "MUL", "DIV", "AND", "OR", "XOR",
             "LSHIFT", "RSHIFT", "RANDOM"}
DIRECTIVES = {".alias", ".const", ".tag"}
ALL_OPS = ACTIONS | BRANCH_OPS | SENSE_OPS | ARITH_OPS | {"MARK", "TAG"}

DIRECTIONS = {"N", "E", "S", "W", "NORTH", "EAST", "SOUTH", "WEST", "RANDOM", "HERE"}
TARGETS = {"FOOD", "WALL", "NEST", "ANT", "EMPTY"}
CHANNELS = {"CH_RED", "CH_BLUE", "CH_GREEN", "CH_YELLOW"}
BUILTINS = DIRECTIONS | TARGETS | CHANNELS


def preprocess(source_path: Path, defines: dict | None = None,
               included: set | None = None) -> list[str]:
    if defines is None:
        defines = {}
    if included is None:
        included = set()

    source_path = source_path.resolve()
    if source_path in included:
        return [f"; [already included {source_path.name}]"]
    included.add(source_path)

    lines = source_path.read_text().splitlines()
    output = []
    skip_depth = 0

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("#endif"):
            skip_depth = max(0, skip_depth - 1)
            continue
        if stripped.startswith("#ifdef"):
            name = stripped.split(None, 1)[1].strip()
            if name not in defines:
                skip_depth += 1
            continue
        if stripped.startswith("#ifndef"):
            name = stripped.split(None, 1)[1].strip()
            if name in defines:
                skip_depth += 1
            continue
        if skip_depth > 0:
            continue

        if stripped.startswith("#define"):
            parts = stripped.split(None, 2)
            if len(parts) >= 3:
                defines[parts[1]] = parts[2]
            elif len(parts) == 2:
                defines[parts[1]] = ""
            continue

        if stripped.startswith("#include"):
            match = re.match(r'#include\s+"([^"]+)"', stripped)
            if match:
                inc_path = LIB_DIR / match.group(1)
                if not inc_path.exists():
                    inc_path = source_path.parent / match.group(1)
                if inc_path.exists():
                    output.extend(preprocess(inc_path, defines, included))
                else:
                    output.append(f"; ERROR: include not found: {match.group(1)}")
            continue

        # Apply defines (longest match first to avoid partial replacement)
        for name in sorted(defines, key=len, reverse=True):
            line = line.replace(name, defines[name])

        output.append(line)

    return output


def parse(lines: list[str]):
    """Parse preprocessed lines into structured data for analysis."""
    labels: dict[str, int] = {}
    aliases: dict[str, str] = {}
    instructions: list[tuple[int, str, list[str]]] = []  # (src_line, op, args)
    label_refs: dict[str, list[int]] = {}  # label -> [src_lines that reference it]
    pc = 0

    for src_line, line in enumerate(lines):
        stripped = line.strip()
        comment_pos = stripped.find(";")
        if comment_pos >= 0:
            stripped = stripped[:comment_pos].strip()
        if not stripped:
            continue

        if stripped.endswith(":"):
            label = stripped[:-1].strip()
            if label in labels:
                warn(f"duplicate label '{label}' (first at pc={labels[label]}, again at pc={pc})")
            labels[label] = pc
            continue

        tokens = stripped.split()
        op = tokens[0]
        args = tokens[1:]

        if op == ".alias" and len(args) >= 2:
            aliases[args[0]] = args[1]
            continue
        if op == ".const" and len(args) >= 2:
            continue
        if op == ".tag":
            continue

        if op in ALL_OPS:
            instructions.append((src_line, op, args))
            # Track label references (last arg of branches, CALL arg 2)
            if op in BRANCH_OPS:
                for arg in args:
                    if (not re.match(r'^r[0-7]$', arg)
                            and not re.match(r'^-?\d+$', arg)
                            and arg not in BUILTINS
                            and arg not in aliases):
                        label_refs.setdefault(arg, []).append(src_line)
            pc += 1

    return labels, aliases, instructions, label_refs


def resolve_register(token: str, aliases: dict[str, str]) -> str | None:
    """Resolve a token to a register name, or None if not a register."""
    if re.match(r'^r[0-7]$', token):
        return token
    if token in aliases:
        val = aliases[token]
        if re.match(r'^r[0-7]$', val):
            return val
    return None


def analyze(lines: list[str]):
    labels, aliases, instructions, label_refs = parse(lines)

    # Register usage (resolve aliases)
    regs_used = set()
    for _, op, args in instructions:
        for arg in args:
            reg = resolve_register(arg, aliases)
            if reg:
                regs_used.add(reg)

    # Undefined label references
    undefined = []
    for ref, src_lines in label_refs.items():
        if ref not in labels:
            undefined.append((ref, src_lines))

    # Unused labels (defined but never referenced)
    referenced_labels = set(label_refs.keys())
    unused = [l for l in labels if l not in referenced_labels and l != "main"]

    # Op count between actions (linear scan, not control-flow aware)
    action_count = 0
    max_linear_gap = 0
    current_gap = 0
    gap_start_line = 0
    long_gaps = []
    for src_line, op, args in instructions:
        if op in ACTIONS:
            if current_gap > max_linear_gap:
                max_linear_gap = current_gap
            if current_gap > MAX_OPS_PER_TICK:
                long_gaps.append((gap_start_line, current_gap))
            current_gap = 0
            action_count += 1
        else:
            if current_gap == 0:
                gap_start_line = src_line
            current_gap += 1

    total = len(instructions)
    err = sys.stderr
    print(f"=== Static Analysis ===", file=err)
    print(f"Instructions: {total}  Actions: {action_count}  Labels: {len(labels)}  Branches: {sum(1 for _, op, _ in instructions if op in BRANCH_OPS)}", file=err)
    print(f"Registers: {' '.join(sorted(regs_used))} ({8 - len(regs_used)} free)", file=err)
    if aliases:
        print(f"Aliases: {', '.join(f'{k}={v}' for k, v in aliases.items())}", file=err)

    if undefined:
        print(f"\nERROR: Undefined labels:", file=err)
        for ref, src_lines in undefined:
            print(f"  '{ref}' referenced at lines {src_lines}", file=err)

    if unused:
        print(f"\nWARN: Unused labels: {', '.join(unused)}", file=err)

    if long_gaps:
        print(f"\nWARN: Possible >64 op paths (linear scan):", file=err)
        for start, count in long_gaps:
            print(f"  {count} ops starting near line {start}", file=err)

    print(f"\nMax linear gap between actions: {max_linear_gap} ops", file=err)
    print(f"=== End Analysis ===", file=err)

    return len(undefined) == 0


MAX_OPS_PER_TICK = 64


def strip_comments_and_blanks(lines: list[str]) -> list[str]:
    """Remove pure comment lines and blank lines, keep inline comments."""
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        out.append(line)
    return out


def strip_debug_symbols(lines: list[str]) -> list[str]:
    """Remove .alias, .tag, .const, TAG, inline comments, and anonymize labels."""
    import re
    # Collect .const and .alias definitions for expansion
    consts = {}
    aliases = {}
    for line in lines:
        s = line.strip()
        comment_pos = s.find(";")
        if comment_pos >= 0:
            s = s[:comment_pos].strip()
        if s.startswith(".const"):
            parts = s.split(None, 2)
            if len(parts) >= 3:
                consts[parts[1]] = parts[2]
        elif s.startswith(".alias"):
            parts = s.split()
            if len(parts) >= 3:
                aliases[parts[1]] = parts[2]

    # Collect state labels (non-internal labels)
    state_names = []
    for line in lines:
        s = line.strip()
        if s.endswith(":") and not s.startswith("__") and not s.startswith("."):
            state_names.append(s[:-1])
    remap = {name: f"_s{i}" for i, name in enumerate(state_names)}

    out = []
    for line in lines:
        s = line.strip()
        if s.startswith((".alias", ".tag", ".const")):
            continue
        if re.match(r'\s*TAG\s', line):
            continue
        # Strip inline comments
        comment_pos = line.find(";")
        if comment_pos >= 0:
            line = line[:comment_pos].rstrip()
            if not line:
                continue
        # Expand .const and .alias references
        for name, value in consts.items():
            line = re.sub(rf'\b{re.escape(name)}\b', value, line)
        for name, value in aliases.items():
            line = re.sub(rf'\b{re.escape(name)}\b', value, line)
        if s.endswith(":") and s[:-1] in remap:
            out.append(f"{remap[s[:-1]]}:")
        elif re.match(r'\s*(JMP|JNE|JEQ|JGT|JLT|CALL)\s', line):
            for old, new in remap.items():
                line = re.sub(rf'\b{re.escape(old)}\b', new, line)
            out.append(line)
        else:
            out.append(line)
    return out


def compile_program(source_path: Path, do_analyze: bool = False,
                    do_strip: bool = False):
    lines = preprocess(source_path)

    if do_analyze:
        analyze(lines)
        return

    if do_strip:
        lines = strip_comments_and_blanks(lines)
        lines = strip_debug_symbols(lines)

    sys.stdout.write("\n".join(lines))


def warn(msg):
    print(f"WARN: {msg}", file=sys.stderr)


def main():
    if len(sys.argv) < 2:
        print("Usage: swarm antssembly <source.ant> [--analyze] [--strip]", file=sys.stderr)
        print("  --analyze  Run static analysis", file=sys.stderr)
        print("  --strip    Strip comments, blanks, and debug symbols", file=sys.stderr)
        sys.exit(1)

    source = Path(sys.argv[1])
    flags = set(sys.argv[2:])

    if not source.exists():
        print(f"Error: {source} not found", file=sys.stderr)
        sys.exit(1)

    compile_program(
        source,
        do_analyze="--analyze" in flags,
        do_strip="--strip" in flags,
    )


if __name__ == "__main__":
    main()
