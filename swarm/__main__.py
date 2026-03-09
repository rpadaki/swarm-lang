"""Swarm Language compiler toolchain."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="swarm",
        description="Swarm Language compiler toolchain",
    )
    parser.add_argument("-V", "--version", action="version", version="swarm 0.1.0")
    sub = parser.add_subparsers(dest="command")

    # compile (also the default when a .sw file is passed directly)
    p_compile = sub.add_parser("compile", help="Compile .sw to antssembly")
    _add_compile_args(p_compile)

    # check
    p_check = sub.add_parser("check", help="Lint / check for warnings")
    p_check.add_argument("file", help=".sw file to check")

    # fmt
    p_fmt = sub.add_parser("fmt", help="Format a .sw file")
    p_fmt.add_argument("file", help=".sw file to format")
    p_fmt.add_argument("--in-place", action="store_true", help="Overwrite file in place")

    # stats
    p_stats = sub.add_parser("stats", help="Print program statistics")
    p_stats.add_argument("file", help=".sw file to analyze")

    # lsp
    sub.add_parser("lsp", help="Start the LSP server")

    # antssembly
    p_asm = sub.add_parser("antssembly", help="Preprocess a .ant file")
    p_asm.add_argument("file", help=".ant file to preprocess")
    p_asm.add_argument("--analyze", action="store_true", help="Analyze only")
    p_asm.add_argument("--strip", action="store_true", help="Strip comments and aliases")

    # If first arg looks like a .sw file, treat as implicit compile
    if len(sys.argv) > 1 and sys.argv[1].endswith(".sw") and not sys.argv[1].startswith("-"):
        sys.argv.insert(1, "compile")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help(sys.stderr)
        sys.exit(1)
    elif args.command == "compile":
        _compile(args)
    elif args.command == "check":
        _check(args)
    elif args.command == "fmt":
        _fmt(args)
    elif args.command == "stats":
        _stats(args)
    elif args.command == "lsp":
        from .lsp import main as lsp_main
        lsp_main()
    elif args.command == "antssembly":
        _antssembly(args)


def _add_compile_args(p):
    p.add_argument("file", help=".sw file to compile")
    p.add_argument("-o", "--output", metavar="FILE", help="Write output to file")
    p.add_argument("-O0", dest="no_opt", action="store_true", help="Disable all optimizations")
    p.add_argument("-s", "--strip", action="store_true", help="Remove debug symbols")


def _compile(args):
    from pathlib import Path
    from .tokenizer import tokenize
    from .parser import Parser
    from .compiler import Compiler, resolve_imports
    from .optimize import OptConfig, OPT_NONE

    src = Path(args.file)
    opt = OPT_NONE if args.no_opt else None
    if args.strip:
        if opt is None:
            opt = OptConfig()
        opt.strip = True

    prog = Parser(tokenize(src.read_text())).parse_program()
    prog, packages, pkg_externs = resolve_imports(prog, src.parent)
    output = Compiler(packages, pkg_externs, opt=opt).compile(prog)

    if args.output:
        out_file = Path(args.output)
        out_file.write_text(output if opt.strip else output + "\n")
        print(f"Wrote {out_file}", file=sys.stderr)
    else:
        print(output)


def _check(args):
    from pathlib import Path
    from .tokenizer import tokenize
    from .parser import Parser
    from .compiler import resolve_imports
    from .linter import check

    path = Path(args.file)
    prog = Parser(tokenize(path.read_text())).parse_program()
    try:
        prog, _packages, _pkg_externs = resolve_imports(prog, source_dir=path.parent)
    except SyntaxError as e:
        print(f"warning: {e}", file=sys.stderr)
    warns = check(prog)
    if warns:
        for w in warns:
            print(f"warning: {w}", file=sys.stderr)
    else:
        print(f"{path}: ok (no warnings)", file=sys.stderr)


def _fmt(args):
    from pathlib import Path
    from .formatter import format_sw

    path = Path(args.file)
    formatted = format_sw(path.read_text())
    if args.in_place:
        path.write_text(formatted)
        print(f"Formatted {path}", file=sys.stderr)
    else:
        sys.stdout.write(formatted)


def _stats(args):
    sys.argv = ["stats", args.file]
    from .stats import main as stats_main
    stats_main()


def _antssembly(args):
    sys.argv = ["antssembly", args.file]
    if args.analyze:
        sys.argv.append("--analyze")
    if args.strip:
        sys.argv.append("--strip")
    from .antssembly import main as asm_main
    asm_main()


if __name__ == "__main__":
    main()
