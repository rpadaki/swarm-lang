"""CLI entry point: uv run swarm [subcommand] [args]

Subcommands:
    compile   Compile a .sw file to antssembly (default)
    check     Lint a .sw file
    fmt       Format a .sw file
    stats     Print stats about a .sw file
    lsp       Start the LSP server
    antssembly  Preprocess a .ant file
"""

import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: swarm <file.sw | subcommand> [args]", file=sys.stderr)
        print("Subcommands: compile, check, fmt, stats, lsp, antssembly", file=sys.stderr)
        sys.exit(1)

    subcommand = sys.argv[1]

    if subcommand == "check":
        sys.argv = sys.argv[1:]  # shift so check sees [check, file, ...]
        from .linter import main as check_main
        check_main()
    elif subcommand == "fmt":
        sys.argv = sys.argv[1:]
        from .formatter import main as fmt_main
        fmt_main()
    elif subcommand == "stats":
        sys.argv = sys.argv[1:]
        from .stats import main as stats_main
        stats_main()
    elif subcommand == "lsp":
        from .lsp import main as lsp_main
        lsp_main()
    elif subcommand == "antssembly":
        sys.argv = sys.argv[1:]
        from .antssembly import main as asm_main
        asm_main()
    elif subcommand == "compile":
        sys.argv = sys.argv[1:]
        _compile()
    else:
        _compile()


def _compile():
    from pathlib import Path
    from .tokenizer import tokenize
    from .parser import Parser
    from .compiler import Compiler, resolve_imports
    from .optimize import OptConfig, OPT_NONE

    if len(sys.argv) < 2:
        print("Usage: swarm <file.sw> [--copy] [-o out.ant] [-O0]", file=sys.stderr)
        sys.exit(1)
    src = Path(sys.argv[1])
    do_copy = "--copy" in sys.argv
    out_file = None
    if "-o" in sys.argv: out_file = Path(sys.argv[sys.argv.index("-o") + 1])

    opt = None  # default: all optimizations
    if "-O0" in sys.argv:
        opt = OPT_NONE
    if "--strip" in sys.argv or "-s" in sys.argv:
        if opt is None:
            opt = OptConfig()
        opt.strip = True

    prog = Parser(tokenize(src.read_text())).parse_program()
    prog, packages, pkg_externs = resolve_imports(prog, src.parent)
    output = Compiler(packages, pkg_externs, opt=opt).compile(prog)

    if out_file:
        out_file.write_text(output + "\n")
        print(f"Wrote {out_file}", file=sys.stderr)
    elif do_copy:
        import subprocess
        subprocess.run(["pbcopy"], input=output.encode(), check=True)
        print("Copied!", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
