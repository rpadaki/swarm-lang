"""
Swarm Language LSP server.

Provides diagnostics, completions, formatting, and hover for .sw files.
Wraps the existing compiler, linter, and formatter.

Usage:
    uv run python -m swarm lsp          # start LSP on stdio
"""

import re
import sys
from pathlib import Path

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from .tokenizer import tokenize
from .parser import Parser
from .compiler import Compiler, resolve_imports, _find_module
from .ast import (
    StateBlock, StateFromBehavior, BehaviorDef, InitBlock, FuncDef, Const,
    RegDecl, TagDecl, BoolDecl, Import, ExportFunc, ExportConst,
)
from .linter import check
from .formatter import format_sw

server = LanguageServer("swarm-lsp", "v0.1.0")

# ── Built-in documentation ────────────────────────────────────────
# NOTE: These dicts are documentation-only — they provide hover docs and
# completions in the LSP.  The compiler does NOT use them; all ant-specific
# knowledge comes from libant via export func / export const.

BUILTIN_FUNCS = {
    "sense": {
        "sig": "sense(type) → direction (1-4) or 0",
        "doc": "Returns direction (N=1, E=2, S=3, W=4) to nearest cell of `type`, or 0 if none visible.\n\n**Arguments:** `FOOD` or `NEST`\n\n```swarm\nscratch = sense(FOOD)\nif scratch != 0 {\n    move(scratch)\n    become try_pickup\n}\n```",
        "insert": "sense(${1|FOOD,NEST|})",
    },
    "probe": {
        "sig": "probe(direction) → cell_type",
        "doc": "Returns cell type at `direction`: `EMPTY` (0), `WALL` (1), `FOOD` (2), `NEST` (3).\n\n**Arguments:** `N`, `E`, `S`, `W`, `HERE`, or a register\n\n```swarm\nscratch = probe(E)\nif scratch != WALL {\n    move(E)\n    become search\n}\n```",
        "insert": "probe(${1|HERE,N,E,S,W|})",
    },
    "smell": {
        "sig": "smell(channel) → direction (1-4) or 0",
        "doc": "Returns direction of strongest pheromone on `channel`, or 0 if none detected.\n\n**Arguments:** `CH_RED`, `CH_BLUE`, `CH_GREEN`, `CH_YELLOW`\n\n```swarm\nscratch = smell(CH_RED)\nif scratch != 0 {\n    move(scratch)\n    become follow_trail\n}\n```",
        "insert": "smell(${1|CH_RED,CH_GREEN,CH_BLUE,CH_YELLOW|})",
    },
    "sniff": {
        "sig": "sniff(channel, direction) → intensity (0-255)",
        "doc": "Returns pheromone intensity on `channel` at `direction`.\n\n**Arguments:**\n- channel: `CH_RED`, `CH_BLUE`, `CH_GREEN`, `CH_YELLOW`\n- direction: `N`, `E`, `S`, `W`, `HERE`, or register\n\n```swarm\nscratch = sniff(CH_RED, N)\nif scratch > 100 { ... }\n```",
        "insert": "sniff(${1|CH_RED,CH_GREEN,CH_BLUE,CH_YELLOW|}, ${2|HERE,N,E,S,W|})",
    },
    "carrying": {
        "sig": "carrying() → 0 | 1",
        "doc": "Returns 1 if the ant is carrying food, 0 otherwise.\n\n```swarm\nif carrying() != 0 { become return_home }\n```",
        "insert": "carrying()",
    },
    "id": {
        "sig": "id() → 0..199",
        "doc": "Returns the ant's unique ID (0-199). All 200 ants run the same program.\n\nUseful for role assignment:\n```swarm\nscratch = id()\nscratch = scratch % 4  // split into 4 groups\n```",
        "insert": "id()",
    },
    "rand": {
        "sig": "rand(max) or rand(lo, hi) → integer",
        "doc": "`rand(max)`: random integer in [0, max).\n`rand(lo, hi)`: random integer in [lo, hi).\n\n```swarm\ndir = rand(4)      // 0..3\ndir = dir + 1      // 1..4 (valid direction)\n\ndir = rand(1, 5)   // 1..4 directly\n```",
        "insert": "rand(${1:4})",
    },
}

BUILTIN_ACTIONS = {
    "move": {
        "sig": "move(direction)",
        "doc": "Move in `direction`. **Consumes a tick.** Auto-sets `last_dir`.\n\n**Directions:** `N`/`NORTH` (1), `E`/`EAST` (2), `S`/`SOUTH` (3), `W`/`WEST` (4), `RANDOM`, `HERE`, or register.\n\n```swarm\nmove(N)\nbecome search\n```",
        "insert": "move(${1|N,E,S,W,RANDOM,HERE,last_dir|})",
    },
    "pickup": {
        "sig": "pickup()",
        "doc": "Pick up food at current cell. **Consumes a tick.**\n\n```swarm\npickup()\nbecome check_carry\n```",
        "insert": "pickup()",
    },
    "drop": {
        "sig": "drop()",
        "doc": "Drop carried food at current cell. **Consumes a tick.**\n\n```swarm\ndrop()\nbecome reset_coords\n```",
        "insert": "drop()",
    },
    "mark": {
        "sig": "mark(channel, intensity)",
        "doc": "Add pheromone. Additive (capped at 255). **Does NOT consume a tick.**\n\n**Channels:** `CH_RED`, `CH_BLUE`, `CH_GREEN`, `CH_YELLOW`\n**Intensity:** 0-255 (literal or register)\n\n```swarm\nmark(CH_GREEN, 50)\nmark(CH_RED, mark_str)  // register value\n```",
        "insert": "mark(${1|CH_RED,CH_GREEN,CH_BLUE,CH_YELLOW|}, ${2:intensity})",
    },
    "set_tag": {
        "sig": "set_tag(tag)",
        "doc": "Override heatmap tag mid-state. **Does NOT consume a tick.**\nUseful for visual debugging of sub-states.\n\n```swarm\nset_tag(stuck)\n```",
        "insert": "set_tag(${1:tag})",
    },
}

BUILTIN_CONSTANTS = {
    "N":          ("Direction North (1)", "direction"),
    "NORTH":      ("Direction North (1)", "direction"),
    "E":          ("Direction East (2)", "direction"),
    "EAST":       ("Direction East (2)", "direction"),
    "S":          ("Direction South (3)", "direction"),
    "SOUTH":      ("Direction South (3)", "direction"),
    "W":          ("Direction West (4)", "direction"),
    "WEST":       ("Direction West (4)", "direction"),
    "HERE":       ("Current cell (direction 0)", "direction"),
    "RANDOM":     ("Random direction", "direction"),
    "EMPTY":      ("Cell type: empty (0)", "cell_type"),
    "WALL":       ("Cell type: wall (1)", "cell_type"),
    "FOOD":       ("Cell type: food (2) — also sense target", "cell_type"),
    "NEST":       ("Cell type: nest (3) — also sense target", "cell_type"),
    "CH_RED":     ("Pheromone channel: red", "channel"),
    "CH_BLUE":    ("Pheromone channel: blue", "channel"),
    "CH_GREEN":   ("Pheromone channel: green", "channel"),
    "CH_YELLOW":  ("Pheromone channel: yellow", "channel"),
}

KEYWORDS = [
    "state", "behavior", "init", "func", "const", "register", "tag", "bool",
    "if", "else", "while", "loop", "match", "case", "default",
    "become", "break", "continue", "exit", "asm",
    "import", "export", "package", "using", "extern", "action", "volatile", "stable", "local",
]

KEYWORD_SNIPPETS = {
    "state":    ("state ${1:name} {\n\t$0\n}", "Define a new state"),
    "behavior": ("behavior ${1:name} {\n\texit ${2:done}\n\t$0\n}", "Define a reusable behavior with exits"),
    "init":     ("init {\n\tbecome ${1:state}\n}", "Init block — runs once at spawn"),
    "func":     ("func ${1:name}() {\n\t$0\n}", "Inline function (expanded at call sites)"),
    "const":    ("const ${1:NAME} = ${2:value}", "Compile-time constant"),
    "register": ("register (\n\t${1:name}(${2:binding}),\n\t$0\n)", "Declare named registers with bindings (max 8)"),
    "if":       ("if ${1:condition} {\n\t$0\n}", "Conditional branch"),
    "while":    ("while ${1:condition} {\n\t$0\n}", "While loop"),
    "loop":     ("loop {\n\t$0\n}", "Infinite loop (use break to exit)"),
    "match":    ("match ${1:expr} {\n\tcase ${2:value} {\n\t\t$0\n\t}\n\tdefault {\n\t}\n}", "Match on value"),
    "become":   ("become ${1:state}", "Instant transition (no tick consumed)"),
    "package":  ("package ${1:name}", "Declare package name"),
    "using":    ("using ${1:name}", "Import and use package namespace"),
    "extern":   ("extern register ${1:name}", "Declare optional extern register (DCE'd if unbound)"),
    "action":   ("action func ${1:name}() {\n\t$0\n}", "Action function (consumes a tick)"),
    "local":    ("local ${1:name}", "Compiler-assigned temporary register"),
}

# ── Helpers ───────────────────────────────────────────────────────

def _compile_source(src: str, source_dir: Path | None = None):
    errors = []
    try:
        prog = Parser(tokenize(src)).parse_program()
        prog, packages, pkg_externs = resolve_imports(prog, source_dir)
        Compiler(packages, pkg_externs).compile(prog)
    except SyntaxError as e:
        line = _extract_line(str(e))
        errors.append((line, str(e)))
    except Exception as e:
        line = _extract_line(str(e))
        errors.append((line, str(e)))
    return errors


def _lint_source(src: str, source_dir: Path | None = None):
    try:
        prog = Parser(tokenize(src)).parse_program()
        prog, _packages, _pkg_externs = resolve_imports(prog, source_dir)
        warnings = check(prog)
        results = []
        for w in warnings:
            line, sc, ec = _find_warning_location(src, w)
            results.append((line, sc, ec, w))
        return results
    except Exception:
        return []


def _find_warning_location(src: str, warning: str) -> tuple[int, int | None, int | None]:
    """Find source line and optional column range for a linter warning.

    Returns (line, start_col, end_col). start_col/end_col are None for whole-line.
    """
    # "unused register: 'name'" → find exact name in register declaration
    m = re.match(r"unused register: '(\w+)'", warning)
    if m:
        name = m.group(1)
        for i, line in enumerate(src.split("\n")):
            if re.search(rf'\bregister\b', line):
                nm = re.search(rf'\b{re.escape(name)}\b', line)
                if nm:
                    return (i, nm.start(), nm.end())
    # "undeclared identifier: 'name'" → find first usage in code
    m = re.match(r"undeclared identifier: '(\w+)'", warning)
    if m:
        name = m.group(1)
        for i, line in enumerate(src.split("\n")):
            # Skip declarations
            if re.match(r'\s*(register|const|tag|bool|state|behavior|func|import|export)\b', line):
                continue
            nm = re.search(rf'\b{re.escape(name)}\b', line)
            if nm:
                return (i, nm.start(), nm.end())
    # "unreachable state: 'name'" → find the state definition
    m = re.match(r"unreachable state: '(\w+)'", warning)
    if m:
        name = m.group(1)
        for i, line in enumerate(src.split("\n")):
            sm = re.search(rf'\bstate\s+({re.escape(name)})\b', line)
            if sm:
                return (i, sm.start(1), sm.end(1))
    # "state 'name': unwired exits" → find the state
    m = re.match(r"state '(\w+)':", warning)
    if m:
        name = m.group(1)
        for i, line in enumerate(src.split("\n")):
            sm = re.search(rf'\bstate\s+({re.escape(name)})\b', line)
            if sm:
                return (i, sm.start(1), sm.end(1))
    return (0, None, None)


def _extract_line(msg: str) -> int:
    m = re.search(r"line (\d+)", msg)
    return int(m.group(1)) - 1 if m else 0


def _collect_symbols(src: str, source_dir: Path | None = None):
    symbols = {
        "states": [], "behaviors": {}, "registers": [],
        "consts": {}, "funcs": [], "efuncs": {}, "tags": [], "bools": [],
        "imports": [],
    }
    try:
        prog = Parser(tokenize(src)).parse_program()
    except Exception:
        return symbols

    for node in prog:
        if isinstance(node, Import):
            symbols["imports"].append(node.path)
        if isinstance(node, (StateBlock, StateFromBehavior)):
            symbols["states"].append(node.name)
        if isinstance(node, BehaviorDef):
            symbols["behaviors"][node.name] = node
        if isinstance(node, RegDecl):
            symbols["registers"] = node.names
        if isinstance(node, Const):
            symbols["consts"][node.name] = node.value
        if isinstance(node, FuncDef):
            symbols["funcs"].append(node.name)
        if isinstance(node, ExportFunc):
            symbols["efuncs"][node.name] = node
        if isinstance(node, ExportConst):
            symbols["consts"][node.name] = node.value
        if isinstance(node, TagDecl):
            symbols["tags"].append(node.name)
        if isinstance(node, BoolDecl):
            symbols["bools"].extend(node.names)

    # Resolve imports for symbol collection
    for imp in symbols["imports"]:
        mod_path = _find_module(imp, source_dir)
        if mod_path:
            try:
                mod_prog = Parser(tokenize(mod_path.read_text())).parse_program()
                for m in mod_prog:
                    if isinstance(m, ExportFunc):
                        symbols["efuncs"][m.name] = m
                    elif isinstance(m, ExportConst):
                        symbols["consts"][m.name] = m.value
            except Exception:
                pass

    return symbols


def _word_at(line: str, col: int) -> str | None:
    for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", line):
        if m.start() <= col <= m.end():
            return m.group()
    return None


def _find_definition(src: str, word: str) -> tuple[int, int] | None:
    """Find the line and column of a declaration for `word`."""
    esc = re.escape(word)
    patterns = [
        rf'\bstate\s+({esc})\s*[{{=]',
        rf'\bbehavior\s+({esc})\s*[{{(]',
        rf'\bfunc\s+({esc})\s*\(',
        rf'\bconst\s+({esc})\s*=',
        rf'\btag\s+(?:\d+\s+)?({esc})\b',
        rf'\bexit\s+({esc})\b',
        rf'\bexport\s+func\s+({esc})\s*\(',
        rf'\bexport\s+const\s+({esc})\s*=',
    ]
    reg_pat = re.compile(rf'\bregister\s+(.*)', re.MULTILINE)
    for i, line in enumerate(src.split("\n")):
        for pat in patterns:
            m = re.search(pat, line)
            if m:
                return (i, m.start(1))
        m = reg_pat.search(line)
        if m:
            for rm in re.finditer(r'[A-Za-z_]\w*', m.group(1)):
                if rm.group() == word:
                    return (i, m.start(1) + rm.start())
    return None


# ── LSP Handlers ──────────────────────────────────────────────────

@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def did_open(params: lsp.DidOpenTextDocumentParams):
    _validate(params.text_document.uri, params.text_document.text)


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
def did_change(params: lsp.DidChangeTextDocumentParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    _validate(params.text_document.uri, doc.source)


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def did_save(params: lsp.DidSaveTextDocumentParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    _validate(params.text_document.uri, doc.source)


def _source_dir(uri: str) -> Path | None:
    if uri.startswith("file://"):
        return Path(uri[7:]).parent
    return None

def _validate(uri: str, src: str):
    diagnostics = []
    sd = _source_dir(uri)

    for line, msg in _compile_source(src, sd):
        diagnostics.append(lsp.Diagnostic(
            range=lsp.Range(
                start=lsp.Position(line=max(line, 0), character=0),
                end=lsp.Position(line=max(line, 0), character=1000),
            ),
            severity=lsp.DiagnosticSeverity.Error,
            source="swarm",
            message=msg,
        ))

    for line, sc, ec, msg in _lint_source(src, sd):
        is_unused = "unused" in msg
        is_undeclared = "undeclared" in msg
        start_char = sc if sc is not None else 0
        end_char = ec if ec is not None else 1000
        if is_unused:
            severity = lsp.DiagnosticSeverity.Hint
            tags = [lsp.DiagnosticTag.Unnecessary]
        elif is_undeclared:
            severity = lsp.DiagnosticSeverity.Error
            tags = None
        else:
            severity = lsp.DiagnosticSeverity.Warning
            tags = None
        diagnostics.append(lsp.Diagnostic(
            range=lsp.Range(
                start=lsp.Position(line=max(line, 0), character=start_char),
                end=lsp.Position(line=max(line, 0), character=end_char),
            ),
            severity=severity,
            source="swarm-lint",
            message=msg,
            tags=tags,
        ))

    server.text_document_publish_diagnostics(lsp.PublishDiagnosticsParams(
        uri=uri, diagnostics=diagnostics,
    ))


@server.feature(lsp.TEXT_DOCUMENT_COMPLETION, lsp.CompletionOptions(trigger_characters=["(", " "]))
def completions(params: lsp.CompletionParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    sd = _source_dir(params.text_document.uri)
    symbols = _collect_symbols(doc.source, sd)
    items = []

    # Keywords with snippets
    for kw in KEYWORDS:
        if kw in KEYWORD_SNIPPETS:
            snippet, detail = KEYWORD_SNIPPETS[kw]
            items.append(lsp.CompletionItem(
                label=kw, kind=lsp.CompletionItemKind.Keyword,
                detail=detail,
                insert_text=snippet,
                insert_text_format=lsp.InsertTextFormat.Snippet,
            ))
        else:
            items.append(lsp.CompletionItem(
                label=kw, kind=lsp.CompletionItemKind.Keyword,
            ))

    # Sense functions
    for name, info in BUILTIN_FUNCS.items():
        items.append(lsp.CompletionItem(
            label=name, kind=lsp.CompletionItemKind.Function,
            detail=info["sig"],
            documentation=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=info["doc"]),
            insert_text=info["insert"],
            insert_text_format=lsp.InsertTextFormat.Snippet,
        ))

    # Actions
    for name, info in BUILTIN_ACTIONS.items():
        items.append(lsp.CompletionItem(
            label=name, kind=lsp.CompletionItemKind.Function,
            detail=info["sig"],
            documentation=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=info["doc"]),
            insert_text=info["insert"],
            insert_text_format=lsp.InsertTextFormat.Snippet,
        ))

    # Constants
    for name, (doc, category) in BUILTIN_CONSTANTS.items():
        items.append(lsp.CompletionItem(
            label=name, kind=lsp.CompletionItemKind.Constant,
            detail=category, documentation=doc,
        ))

    # User-declared states
    for name in symbols["states"]:
        items.append(lsp.CompletionItem(
            label=name, kind=lsp.CompletionItemKind.Class,
            detail="state",
        ))

    # User-declared behaviors
    for name, beh in symbols["behaviors"].items():
        params_str = f"({', '.join(beh.params)})" if beh.params else ""
        exits = ", ".join(beh.exits)
        doc_str = f"Exits: {exits}" if exits else ""
        items.append(lsp.CompletionItem(
            label=name, kind=lsp.CompletionItemKind.Class,
            detail=f"behavior{params_str}",
            documentation=doc_str,
        ))

    # User-declared registers
    for name in symbols["registers"]:
        special = ""
        if name == "dx":       special = " — horizontal displacement from nest"
        elif name == "dy":     special = " — vertical displacement from nest"
        elif name == "last_dir": special = " — last move direction (auto-set)"
        elif name in ("next_st", "next_state", "next"): special = " — state dispatch index (auto-set)"
        items.append(lsp.CompletionItem(
            label=name, kind=lsp.CompletionItemKind.Variable,
            detail=f"register{special}",
        ))

    # User-declared constants
    for name, value in symbols["consts"].items():
        items.append(lsp.CompletionItem(
            label=name, kind=lsp.CompletionItemKind.Constant,
            detail=f"const = {value}",
        ))

    # User-declared funcs
    for name in symbols["funcs"]:
        items.append(lsp.CompletionItem(
            label=name, kind=lsp.CompletionItemKind.Function,
            detail="func (inline)",
            insert_text=f"{name}()",
            insert_text_format=lsp.InsertTextFormat.PlainText,
        ))

    # Imported / exported functions
    for name, ef in symbols["efuncs"].items():
        params_str = ", ".join(ef.params)
        ret_str = f" -> {ef.ret}" if ef.ret else ""
        sig = f"{name}({params_str}){ret_str}"
        if ef.params:
            placeholders = ", ".join(f"${{{i+1}:{p}}}" for i, p in enumerate(ef.params))
            insert = f"{name}({placeholders})"
        else:
            insert = f"{name}()"
        items.append(lsp.CompletionItem(
            label=name, kind=lsp.CompletionItemKind.Function,
            detail=sig,
            insert_text=insert,
            insert_text_format=lsp.InsertTextFormat.Snippet,
        ))

    # Bools
    for name in symbols["bools"]:
        items.append(lsp.CompletionItem(
            label=name, kind=lsp.CompletionItemKind.Variable,
            detail="bool (bit-packed flag)",
        ))

    # Tags
    for name in symbols["tags"]:
        items.append(lsp.CompletionItem(
            label=name, kind=lsp.CompletionItemKind.EnumMember,
            detail="tag",
        ))

    return lsp.CompletionList(is_incomplete=False, items=items)


@server.feature(lsp.TEXT_DOCUMENT_HOVER)
def hover(params: lsp.HoverParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    lines = doc.source.split("\n")
    if params.position.line >= len(lines):
        return None
    line = lines[params.position.line]
    word = _word_at(line, params.position.character)
    if not word:
        return None

    if word in BUILTIN_FUNCS:
        info = BUILTIN_FUNCS[word]
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=f"```\n{info['sig']}\n```\n{info['doc']}",
        ))

    if word in BUILTIN_ACTIONS:
        info = BUILTIN_ACTIONS[word]
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=f"```\n{info['sig']}\n```\n{info['doc']}",
        ))

    if word in BUILTIN_CONSTANTS:
        doc_str, category = BUILTIN_CONSTANTS[word]
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=f"**{word}** ({category}) — {doc_str}",
        ))

    sd = _source_dir(params.text_document.uri)
    symbols = _collect_symbols(doc.source, sd)

    if word in symbols["efuncs"]:
        ef = symbols["efuncs"][word]
        params_str = ", ".join(ef.params)
        ret_str = f" -> {ef.ret}" if ef.ret else ""
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=f"```swarm\nexport func {word}({params_str}){ret_str}\n```\n*from libant*",
        ))

    if word in symbols["consts"]:
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=f"```swarm\nconst {word} = {symbols['consts'][word]}\n```",
        ))

    if word in symbols["behaviors"]:
        beh = symbols["behaviors"][word]
        params_str = f"({', '.join(beh.params)})" if beh.params else ""
        exits_str = "\n".join(f"    exit {e}" for e in beh.exits)
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=f"```swarm\nbehavior {word}{params_str} {{\n{exits_str}\n    ...\n}}\n```",
        ))

    if word in symbols["states"]:
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=f"**state** `{word}`",
        ))

    if word in symbols["registers"]:
        idx = symbols["registers"].index(word) + 1
        special = ""
        if word == "dx":       special = "\n\nHorizontal displacement from nest (auto-updated after move)"
        elif word == "dy":     special = "\n\nVertical displacement from nest (auto-updated after move)"
        elif word == "last_dir": special = "\n\nLast move direction (auto-set by `move()`)"
        elif word in ("next_st", "next_state", "next"): special = "\n\nState dispatch index (legacy, no longer auto-set)"
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=f"**register** `{word}` → `r{idx}`{special}",
        ))

    if word in symbols["bools"]:
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=f"**bool** `{word}` — bit-packed flag (0 or 1)",
        ))

    return None


@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
def definition(params: lsp.DefinitionParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    lines = doc.source.split("\n")
    if params.position.line >= len(lines):
        return None
    word = _word_at(lines[params.position.line], params.position.character)
    if not word:
        return None
    # Try local definition first
    loc = _find_definition(doc.source, word)
    if loc:
        line, col = loc
        return lsp.Location(
            uri=params.text_document.uri,
            range=lsp.Range(
                start=lsp.Position(line=line, character=col),
                end=lsp.Position(line=line, character=col + len(word)),
            ),
        )
    # Try imported modules
    sd = _source_dir(params.text_document.uri)
    symbols = _collect_symbols(doc.source, sd)
    for imp in symbols["imports"]:
        mod_path = _find_module(imp, sd)
        if mod_path:
            mod_src = mod_path.read_text()
            loc = _find_definition(mod_src, word)
            if loc:
                line, col = loc
                return lsp.Location(
                    uri=f"file://{mod_path}",
                    range=lsp.Range(
                        start=lsp.Position(line=line, character=col),
                        end=lsp.Position(line=line, character=col + len(word)),
                    ),
                )
    return None


@server.feature(lsp.TEXT_DOCUMENT_FORMATTING)
def formatting(params: lsp.DocumentFormattingParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    try:
        formatted = format_sw(doc.source)
    except Exception:
        return []
    lines = doc.source.split("\n")
    return [lsp.TextEdit(
        range=lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=len(lines), character=0),
        ),
        new_text=formatted,
    )]


# ── Main ──────────────────────────────────────────────────────────

def main():
    server.start_io()


if __name__ == "__main__":
    main()
