"""
Quick stats about a .sw (Swarm Language) program.

Counts states, behaviors, registers, total lines, and estimated antssembly
instruction count (excluding .alias/.tag directives).

Usage:
    uv run swarm stats program.sw
"""

import sys
from pathlib import Path

from .tokenizer import tokenize
from .parser import Parser
from .compiler import Compiler, resolve_imports
from .ast import (
    StateBlock, StateFromBehavior, BehaviorDef, InitBlock, FuncDef, Const,
    RegDecl,
)


def stats(path: Path):
    src = path.read_text()
    lines = src.split("\n")
    total_lines = len(lines)
    non_blank = sum(1 for l in lines if l.strip())
    comment_lines = sum(1 for l in lines if l.strip().startswith("//"))

    prog = Parser(tokenize(src)).parse_program()

    state_count = 0
    behavior_count = 0
    register_names = []
    func_count = 0
    const_count = 0
    has_init = False

    for node in prog:
        if isinstance(node, (StateBlock, StateFromBehavior)):
            state_count += 1
        elif isinstance(node, BehaviorDef):
            behavior_count += 1
        elif isinstance(node, RegDecl):
            register_names = node.names
        elif isinstance(node, FuncDef):
            func_count += 1
        elif isinstance(node, Const):
            const_count += 1
        elif isinstance(node, InitBlock):
            has_init = True

    # Compile and count instructions
    prog2 = Parser(tokenize(src)).parse_program()
    prog2, packages, pkg_externs = resolve_imports(prog2, path.parent)
    compiler = Compiler(packages, pkg_externs)
    output = compiler.compile(prog2)
    output_lines = output.split("\n")

    total_asm = 0
    directives = 0
    labels = 0
    instructions = 0
    for line in output_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(".alias") or stripped.startswith(".tag"):
            directives += 1
        elif stripped.endswith(":"):
            labels += 1
        else:
            instructions += 1
        total_asm += 1

    print(f"File:           {path}")
    print(f"Total lines:    {total_lines}")
    print(f"Non-blank:      {non_blank}")
    print(f"Comment lines:  {comment_lines}")
    print(f"")
    print(f"Constants:      {const_count}")
    print(f"Registers:      {len(register_names)}/8 ({', '.join(register_names) if register_names else 'none'})")
    print(f"States:         {state_count}")
    print(f"Behaviors:      {behavior_count}")
    print(f"Functions:      {func_count}")
    print(f"Init block:     {'yes' if has_init else 'no'}")
    print(f"")
    print(f"Compiled output:")
    print(f"  Directives:   {directives} (.alias, .tag)")
    print(f"  Labels:       {labels}")
    print(f"  Instructions: {instructions}")
    print(f"  Total lines:  {total_asm}")


def main():
    if len(sys.argv) < 2:
        print("Usage: swarm stats <file.sw>", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    stats(path)


if __name__ == "__main__":
    main()
