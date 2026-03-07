"""
Swarm Language LSP server.

Provides diagnostics, completions, formatting, hover, semantic tokens,
document symbols, and go-to-definition for .sw files.

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
from .compiler import Compiler, resolve_imports, _find_module, _load_package
from .ast import (
    StateBlock, StateFromBehavior, BehaviorDef, InitBlock, FuncDef, Const,
    RegDecl, TagDecl, BoolDecl, Import, ExportFunc, ExportConst, UsingDecl,
    PackageDecl,
)
from .linter import check
from .formatter import format_sw

server = LanguageServer("swarm-lsp", "v0.1.0")

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

# ── Semantic Token Types ──────────────────────────────────────────

SEMANTIC_TOKEN_TYPES = [
    "namespace",    # 0 — package names
    "type",         # 1 — state / behavior names
    "variable",     # 2 — registers, bools
    "function",     # 3 — func / efunc names
    "enumMember",   # 4 — constants, tags
    "property",     # 5 — qualified member (ant.move)
]
SEMANTIC_TOKEN_MODIFIERS = ["declaration", "definition"]

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
    except Exception:
        return []
    try:
        prog, _packages, _pkg_externs = resolve_imports(prog, source_dir)
    except Exception:
        pass
    try:
        warnings = check(prog)
        results = []
        for w in warnings:
            line, sc, ec = _find_warning_location(src, w)
            results.append((line, sc, ec, w))
        return results
    except Exception:
        return []


def _find_warning_location(src: str, warning: str) -> tuple[int, int | None, int | None]:
    m = re.match(r"unused register: '(\w+)'", warning)
    if m:
        name = m.group(1)
        in_reg = False
        for i, line in enumerate(src.split("\n")):
            if re.search(rf'\bregister\b', line):
                in_reg = True
            if in_reg or re.search(rf'\bregister\b', line):
                nm = re.search(rf'\b{re.escape(name)}\b', line)
                if nm:
                    return (i, nm.start(), nm.end())
            if in_reg and line.strip() == ')':
                in_reg = False
    m = re.match(r"undeclared identifier: '(\w+)'", warning)
    if m:
        name = m.group(1)
        for i, line in enumerate(src.split("\n")):
            if re.match(r'\s*(register|const|tag|bool|state|behavior|func|import|export)\b', line):
                continue
            nm = re.search(rf'\b{re.escape(name)}\b', line)
            if nm:
                return (i, nm.start(), nm.end())
    m = re.match(r"unreachable state: '(\w+)'", warning)
    if m:
        name = m.group(1)
        for i, line in enumerate(src.split("\n")):
            sm = re.search(rf'\bstate\s+({re.escape(name)})\b', line)
            if sm:
                return (i, sm.start(1), sm.end(1))
    m = re.match(r"state '(\w+)':", warning)
    if m:
        name = m.group(1)
        for i, line in enumerate(src.split("\n")):
            sm = re.search(rf'\bstate\s+({re.escape(name)})\b', line)
            if sm:
                return (i, sm.start(1), sm.end(1))
    m = re.match(r"stale read of '(\w+)'.* \[line (\d+)\]", warning)
    if m:
        name = m.group(1)
        src_line = int(m.group(2)) - 1
        lines = src.split("\n")
        if 0 <= src_line < len(lines):
            nm = re.search(rf'\b{re.escape(name)}\b', lines[src_line])
            if nm:
                return (src_line, nm.start(), nm.end())
    return (0, None, None)


def _extract_line(msg: str) -> int:
    m = re.search(r"line (\d+)", msg)
    return int(m.group(1)) - 1 if m else 0


def _collect_symbols(src: str, source_dir: Path | None = None):
    symbols = {
        "states": [], "behaviors": {}, "registers": [],
        "consts": {}, "funcs": [], "efuncs": {}, "tags": [], "bools": [],
        "imports": [], "packages": [], "using": set(),
        "import_paths": {},  # pkg_name -> resolved Path
    }
    try:
        prog = Parser(tokenize(src)).parse_program()
    except Exception:
        return symbols

    using_names = set()
    for node in prog:
        if isinstance(node, Import):
            symbols["imports"].append(node.path)
        if isinstance(node, UsingDecl):
            using_names.add(node.name)
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
    symbols["using"] = using_names

    # Resolve imports
    pkg_names = set()
    for imp in symbols["imports"]:
        try:
            pkg_name, exports, _externs = _load_package(imp, source_dir, 0)
            if pkg_name:
                pkg_names.add(pkg_name)
                resolved = _find_module(imp, source_dir)
                if resolved:
                    symbols["import_paths"][pkg_name] = resolved
            # Only bring exports into unqualified scope if `using` is declared
            if pkg_name and pkg_name in using_names:
                for m in exports:
                    if isinstance(m, ExportFunc):
                        symbols["efuncs"][m.name] = m
                    elif isinstance(m, ExportConst):
                        symbols["consts"][m.name] = m.value
            elif not pkg_name:
                # Legacy: no package name, always bring in
                for m in exports:
                    if isinstance(m, ExportFunc):
                        symbols["efuncs"][m.name] = m
                    elif isinstance(m, ExportConst):
                        symbols["consts"][m.name] = m.value
        except Exception:
            pass
    symbols["packages"] = list(pkg_names)

    return symbols


def _word_at(line: str, col: int) -> str | None:
    for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", line):
        if m.start() <= col <= m.end():
            return m.group()
    return None


def _get_docstring(src: str, name: str) -> str | None:
    lines = src.split("\n")
    for i, line in enumerate(lines):
        if re.search(rf'\b(func|const)\s+{re.escape(name)}\b', line) or \
           re.search(rf'\bexport\s+(?:action\s+)?(?:func|const)\s+{re.escape(name)}\b', line):
            doc_lines = []
            j = i - 1
            while j >= 0 and lines[j].strip().startswith("//"):
                doc_lines.append(lines[j].strip().lstrip("/").strip())
                j -= 1
            if doc_lines:
                doc_lines.reverse()
                return "\n".join(doc_lines)
            return None
    return None


def _find_const_docstring(name: str, local_src: str, symbols: dict, sd: Path | None) -> str | None:
    doc = _get_docstring(local_src, name)
    if doc:
        return doc
    for imp in symbols.get("imports", []):
        try:
            resolved = _find_module(imp, sd)
            if not resolved:
                continue
            sw_files = sorted(resolved.glob("*.sw")) if resolved.is_dir() else [resolved]
            for sw_file in sw_files:
                doc = _get_docstring(sw_file.read_text(), name)
                if doc:
                    return doc
        except Exception:
            pass
    return None


def _find_efunc_docstring(name: str, symbols: dict, sd: Path | None) -> str | None:
    # Check local source first
    # Then check imported package files
    for imp in symbols.get("imports", []):
        try:
            resolved = _find_module(imp, sd)
            if not resolved:
                continue
            sw_files = sorted(resolved.glob("*.sw")) if resolved.is_dir() else [resolved]
            for sw_file in sw_files:
                doc = _get_docstring(sw_file.read_text(), name)
                if doc:
                    return doc
        except Exception:
            pass
    return None


def _find_definition(src: str, word: str) -> tuple[int, int] | None:
    esc = re.escape(word)
    patterns = [
        rf'\bstate\s+({esc})\s*[{{=]',
        rf'\bbehavior\s+({esc})\s*[{{(]',
        rf'\bfunc\s+({esc})\s*\(',
        rf'\bconst\s+({esc})\s*=',
        rf'\btag\s+(?:\d+\s+)?({esc})\b',
        rf'\bexit\s+({esc})\b',
        rf'\bexport\s+func\s+({esc})\s*\(',
        rf'\bexport\s+(?:action\s+)?func\s+({esc})\s*\(',
        rf'\bexport\s+const\s+({esc})\s*=',
    ]
    # Extern register: extern register dx, dy, last_dir
    extern_pat = re.compile(rf'\bextern\s+register\s+(.*)')
    for i, line_text in enumerate(src.split("\n")):
        m = extern_pat.search(line_text)
        if m:
            for rm in re.finditer(r'[A-Za-z_]\w*', m.group(1)):
                if rm.group() == word:
                    return (i, m.start(1) + rm.start())
    lines = src.split("\n")
    reg_paren_depth = 0
    for i, line in enumerate(lines):
        for pat in patterns:
            m = re.search(pat, line)
            if m:
                return (i, m.start(1))
        # Inline register: register dir, next_st
        inline = re.match(r'\s*register\s+(\w[\w\s,]*)', line)
        if inline and '(' not in line.split('register', 1)[1].split('//')[0]:
            for rm in re.finditer(r'[A-Za-z_]\w*', inline.group(1)):
                if rm.group() == word:
                    return (i, inline.start(1) + rm.start())
        # Register block: track paren depth
        if re.match(r'\s*register\s*\(', line):
            reg_paren_depth = line.count('(') - line.count(')')
            continue
        if reg_paren_depth > 0:
            entry = re.match(r'\s*([A-Za-z_]\w*)', line)
            if entry and entry.group(1) == word:
                return (i, entry.start(1))
            reg_paren_depth += line.count('(') - line.count(')')
    return None


def _compute_comment_string_ranges(src: str) -> list[tuple[int, int, int, int]]:
    """Return list of (start_line, start_col, end_line, end_col) for comments and strings."""
    ranges = []
    lines = src.split("\n")
    for pat in [r'//[^\n]*', r'/\*[\s\S]*?\*/', r'"[^"]*"']:
        for m in re.finditer(pat, src):
            start = m.start()
            end = m.end()
            sl = src[:start].count("\n")
            sc = start - src[:start].rfind("\n") - 1
            el = src[:end].count("\n")
            ec = end - src[:end].rfind("\n") - 1
            ranges.append((sl, sc, el, ec))
    return ranges


def _in_comment_or_string(line: int, col: int, ranges) -> bool:
    for sl, sc, el, ec in ranges:
        if sl == el:
            if line == sl and sc <= col < ec:
                return True
        else:
            if line == sl and col >= sc:
                return True
            if sl < line < el:
                return True
            if line == el and col < ec:
                return True
    return False


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


# ── Semantic Tokens ──────────────────────────────────────────────

@server.feature(
    lsp.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
    lsp.SemanticTokensRegistrationOptions(
        legend=lsp.SemanticTokensLegend(
            token_types=SEMANTIC_TOKEN_TYPES,
            token_modifiers=SEMANTIC_TOKEN_MODIFIERS,
        ),
        full=True,
    ),
)
def semantic_tokens(params: lsp.SemanticTokensParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    sd = _source_dir(params.text_document.uri)
    symbols = _collect_symbols(doc.source, sd)

    # Build lookup for unqualified names
    lookup = {}
    for name in symbols["packages"]:
        lookup[name] = 0  # namespace
    for name in symbols["states"]:
        lookup[name] = 1  # type
    for name, beh in symbols["behaviors"].items():
        lookup[name] = 1  # type
    for name in symbols["registers"]:
        lookup[name] = 2  # variable
    for name in symbols["bools"]:
        lookup[name] = 2  # variable
    for name in symbols["funcs"]:
        lookup[name] = 3  # function
    for name in symbols["efuncs"]:
        lookup[name] = 3  # function
    for name in symbols["consts"]:
        lookup[name] = 4  # enumMember
    for name in symbols["tags"]:
        lookup[name] = 4  # enumMember

    # Build lookup for qualified members (ant.HERE, ant.move)
    # These apply regardless of `using` — qualified access always works
    qual_member_lookup = {}
    for imp in symbols["imports"]:
        try:
            pkg_name, exports, externs = _load_package(imp, sd, 0)
            if pkg_name:
                for m in exports:
                    if isinstance(m, ExportFunc):
                        qual_member_lookup[m.name] = 3  # function
                    elif isinstance(m, ExportConst):
                        qual_member_lookup[m.name] = 4  # enumMember
                if externs:
                    for name in externs:
                        qual_member_lookup[name] = 2  # variable (extern register)
        except Exception:
            pass

    skip = set(KEYWORDS) | {"asm"}
    cs_ranges = _compute_comment_string_ranges(doc.source)

    data = []
    lines = doc.source.split("\n")
    prev_line = 0
    prev_char = 0

    def _emit(line_idx, col, length, token_type):
        nonlocal prev_line, prev_char
        delta_line = line_idx - prev_line
        delta_char = col if delta_line > 0 else col - prev_char
        data.extend([delta_line, delta_char, length, token_type, 0])
        prev_line = line_idx
        prev_char = col

    for line_idx, line in enumerate(lines):
        # Match qualified names (pkg.member) and plain identifiers
        for m in re.finditer(r'([A-Za-z_]\w*)\.([A-Za-z_]\w*)|([A-Za-z_]\w*)', line):
            col = m.start()
            if _in_comment_or_string(line_idx, col, cs_ranges):
                continue

            if m.group(1) and m.group(2):
                # Qualified: pkg.member
                pkg = m.group(1)
                member = m.group(2)
                if pkg in skip:
                    continue
                # Tag the package part as namespace
                if pkg in lookup:
                    _emit(line_idx, m.start(1), len(pkg), lookup[pkg])
                # Tag the member part based on what it is in the package
                if member in qual_member_lookup:
                    _emit(line_idx, m.start(2), len(member), qual_member_lookup[member])
            else:
                # Plain identifier
                word = m.group(3)
                if word in skip:
                    continue
                if word not in lookup:
                    continue
                _emit(line_idx, col, len(word), lookup[word])

    return lsp.SemanticTokens(data=data)


# ── Contextual Completions ───────────────────────────────────────

@server.feature(lsp.TEXT_DOCUMENT_COMPLETION, lsp.CompletionOptions(trigger_characters=["(", " ", "."]))
def completions(params: lsp.CompletionParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    sd = _source_dir(params.text_document.uri)
    symbols = _collect_symbols(doc.source, sd)

    lines = doc.source.split("\n")
    line_idx = params.position.line
    col = params.position.character
    line = lines[line_idx] if line_idx < len(lines) else ""
    prefix = line[:col].lstrip()

    # After "become " → only state names
    if re.match(r'.*\bbecome\s+\w*$', prefix):
        return lsp.CompletionList(is_incomplete=False, items=[
            lsp.CompletionItem(label=name, kind=lsp.CompletionItemKind.Class, detail="state")
            for name in symbols["states"]
        ])

    # After "if " or "while " → condition context: registers, bools, consts, sensing funcs
    if re.match(r'.*\b(if|while)\s+\w*$', prefix):
        items = []
        for name in symbols["registers"]:
            items.append(lsp.CompletionItem(
                label=name, kind=lsp.CompletionItemKind.Variable, detail="register"))
        for name in symbols["bools"]:
            items.append(lsp.CompletionItem(
                label=name, kind=lsp.CompletionItemKind.Variable, detail="bool"))
        for name, value in symbols["consts"].items():
            items.append(lsp.CompletionItem(
                label=name, kind=lsp.CompletionItemKind.Constant, detail=f"const = {value}"))
        for name, ef in symbols["efuncs"].items():
            if not ef.is_action:
                params_str = ", ".join(ef.params)
                if ef.params:
                    placeholders = ", ".join(f"${{{i+1}:{p}}}" for i, p in enumerate(ef.params))
                    insert = f"{name}({placeholders})"
                else:
                    insert = f"{name}()"
                items.append(lsp.CompletionItem(
                    label=name, kind=lsp.CompletionItemKind.Function,
                    detail=f"{name}({params_str})",
                    insert_text=insert,
                    insert_text_format=lsp.InsertTextFormat.Snippet,
                ))
        return lsp.CompletionList(is_incomplete=False, items=items)

    # After "using " → only package names
    if re.match(r'.*\busing\s+\w*$', prefix):
        return lsp.CompletionList(is_incomplete=False, items=[
            lsp.CompletionItem(label=name, kind=lsp.CompletionItemKind.Module, detail="package")
            for name in symbols["packages"]
        ])

    # After "import " → suggest available library packages (directories)
    if re.match(r'.*\bimport\s+"?[^"]*$', prefix):
        items = []
        lib_dir = Path(__file__).resolve().parent.parent / "lib"
        if lib_dir.is_dir():
            # Find relative path from source to lib
            rel = ""
            if sd:
                try:
                    rel = str(Path("..") / lib_dir.relative_to(sd.parent)) + "/"
                except ValueError:
                    rel = "../lib/"
            for p in sorted(lib_dir.iterdir()):
                if p.is_dir() and not p.name.startswith("."):
                    items.append(lsp.CompletionItem(
                        label=f'"{rel}{p.name}"', kind=lsp.CompletionItemKind.Module,
                        detail=f"package directory",
                        insert_text=f'"{rel}{p.name}"',
                    ))
        return lsp.CompletionList(is_incomplete=False, items=items)

    # After "package.": qualified member access
    dot_match = re.search(r'\b(\w+)\.\w*$', prefix)
    if dot_match:
        pkg = dot_match.group(1)
        items = []
        # Load exports for this specific package
        for imp in symbols["imports"]:
            try:
                pkg_name, exports, externs = _load_package(imp, sd, 0)
                if pkg_name != pkg:
                    continue
                for m in exports:
                    if isinstance(m, ExportFunc):
                        params_str = ", ".join(m.params)
                        ret_str = f" -> {m.ret}" if m.ret else ""
                        sig = f"{m.name}({params_str}){ret_str}"
                        if m.params:
                            placeholders = ", ".join(f"${{{i+1}:{p}}}" for i, p in enumerate(m.params))
                            insert = f"{m.name}({placeholders})"
                        else:
                            insert = f"{m.name}()"
                        action_prefix = "action " if m.is_action else ""
                        items.append(lsp.CompletionItem(
                            label=m.name, kind=lsp.CompletionItemKind.Function,
                            detail=f"{action_prefix}{sig}",
                            insert_text=insert,
                            insert_text_format=lsp.InsertTextFormat.Snippet,
                        ))
                    elif isinstance(m, ExportConst):
                        items.append(lsp.CompletionItem(
                            label=m.name, kind=lsp.CompletionItemKind.Constant,
                            detail=f"const = {m.value}",
                        ))
                if externs:
                    for name in sorted(externs):
                        items.append(lsp.CompletionItem(
                            label=name, kind=lsp.CompletionItemKind.Variable,
                            detail="extern register",
                        ))
            except Exception:
                pass
        return lsp.CompletionList(is_incomplete=False, items=items)

    # Determine if we're at top level or inside a block
    depth = 0
    for l in lines[:line_idx]:
        depth += l.count("{") - l.count("}")
    depth += line[:col].count("{") - line[:col].count("}")

    items = []

    if depth == 0:
        # Top level: structural keywords
        top_kws = ["state", "behavior", "init", "func", "const", "register",
                    "tag", "bool", "import", "export", "package", "using", "extern"]
        for kw in top_kws:
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
    else:
        # Inside a block: statement-level keywords
        stmt_kws = ["if", "else", "while", "loop", "match", "become",
                     "break", "continue", "local"]
        for kw in stmt_kws:
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

        # Registers
        for name in symbols["registers"]:
            items.append(lsp.CompletionItem(
                label=name, kind=lsp.CompletionItemKind.Variable,
                detail="register",
            ))

        # Bools
        for name in symbols["bools"]:
            items.append(lsp.CompletionItem(
                label=name, kind=lsp.CompletionItemKind.Variable,
                detail="bool",
            ))

        # Constants (user + imported)
        for name, value in symbols["consts"].items():
            items.append(lsp.CompletionItem(
                label=name, kind=lsp.CompletionItemKind.Constant,
                detail=f"const = {value}",
            ))

        # Functions (user + imported)
        for name in symbols["funcs"]:
            items.append(lsp.CompletionItem(
                label=name, kind=lsp.CompletionItemKind.Function,
                detail="func (inline)",
                insert_text=f"{name}()",
            ))
        for name, ef in symbols["efuncs"].items():
            params_str = ", ".join(ef.params)
            ret_str = f" -> {ef.ret}" if ef.ret else ""
            sig = f"{name}({params_str}){ret_str}"
            action_prefix = "action " if ef.is_action else ""
            if ef.params:
                placeholders = ", ".join(f"${{{i+1}:{p}}}" for i, p in enumerate(ef.params))
                insert = f"{name}({placeholders})"
            else:
                insert = f"{name}()"
            items.append(lsp.CompletionItem(
                label=name, kind=lsp.CompletionItemKind.Function,
                detail=f"{action_prefix}{sig}",
                insert_text=insert,
                insert_text_format=lsp.InsertTextFormat.Snippet,
            ))

        # State names (for become targets)
        for name in symbols["states"]:
            items.append(lsp.CompletionItem(
                label=name, kind=lsp.CompletionItemKind.Class,
                detail="state",
            ))

        # Tags
        for name in symbols["tags"]:
            items.append(lsp.CompletionItem(
                label=name, kind=lsp.CompletionItemKind.EnumMember,
                detail="tag",
            ))

    return lsp.CompletionList(is_incomplete=False, items=items)


# ── Hover ────────────────────────────────────────────────────────

@server.feature(lsp.TEXT_DOCUMENT_HOVER)
def hover(params: lsp.HoverParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    lines = doc.source.split("\n")
    if params.position.line >= len(lines):
        return None
    line = lines[params.position.line]
    col = params.position.character

    sd = _source_dir(params.text_document.uri)

    # Skip hover inside import strings
    import_match = re.match(r'\s*import\s+"([^"]+)"', line)
    if import_match:
        str_start = line.index(f'"{import_match.group(1)}"')
        str_end = str_start + len(import_match.group(1)) + 2
        if str_start <= col <= str_end:
            return None

    symbols = _collect_symbols(doc.source, sd)

    # Qualified name hover: pkg.member
    qual_match = re.search(r'(\w+)\.(\w+)', line)
    if qual_match and qual_match.start() <= col <= qual_match.end():
        member = qual_match.group(2)
        if member in symbols["efuncs"]:
            ef = symbols["efuncs"][member]
        else:
            # Load from package even without `using`
            pkg = qual_match.group(1)
            ef = None
            for imp in symbols["imports"]:
                try:
                    pkg_name, exports, _ = _load_package(imp, sd, 0)
                    if pkg_name == pkg:
                        for m in exports:
                            if isinstance(m, ExportFunc) and m.name == member:
                                ef = m
                            elif isinstance(m, ExportConst) and m.name == member:
                                return lsp.Hover(contents=lsp.MarkupContent(
                                    kind=lsp.MarkupKind.Markdown,
                                    value=f"```swarm\nconst {member} = {m.value}\n```",
                                ))
                except Exception:
                    pass
        if ef:
            params_str = ", ".join(ef.params)
            action_str = "action " if ef.is_action else ""
            volatile_str = "volatile " if ef.is_volatile else ""
            sig = f"```swarm\nexport {action_str}func {member}({params_str}) -> {volatile_str}{ef.ret or '()'}\n```"
            docstr = _find_efunc_docstring(member, symbols, sd)
            if docstr:
                sig += f"\n\n{docstr}"
            return lsp.Hover(contents=lsp.MarkupContent(
                kind=lsp.MarkupKind.Markdown,
                value=sig,
            ))

    word = _word_at(line, col)
    if not word:
        return None

    if word in symbols["efuncs"]:
        ef = symbols["efuncs"][word]
        params_str = ", ".join(ef.params)
        ret_str = f" -> {ef.ret}" if ef.ret else ""
        action_str = "action " if ef.is_action else ""
        volatile_str = "volatile " if ef.is_volatile else ""
        sig = f"```swarm\nexport {action_str}func {word}({params_str}) -> {volatile_str}{ef.ret or '()'}\n```"
        # Look for docstring in package sources
        doc = _find_efunc_docstring(word, symbols, sd)
        if doc:
            sig += f"\n\n{doc}"
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=sig,
        ))

    if word in symbols["consts"]:
        sig = f"```swarm\nconst {word} = {symbols['consts'][word]}\n```"
        docstr = _find_const_docstring(word, doc.source, symbols, sd)
        if docstr:
            sig += f"\n\n{docstr}"
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=sig,
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
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=f"**register** `{word}` → `r{idx}`",
        ))

    if word in symbols["bools"]:
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=f"**bool** `{word}` — bit-packed flag (0 or 1)",
        ))

    KEYWORD_DOCS = {
        "become": "Instant state transition — does not consume a tick.",
        "state": "Named block of logic. Runs until an action ends the tick.",
        "behavior": "Reusable state template with exit points for wiring.",
        "init": "Runs once when the ant spawns. Must `become` a state.",
        "func": "Inline function — expanded at every call site.",
        "register": "Named storage slot (max 8). Maps to r1–r8 at compile time.",
        "const": "Compile-time constant — replaced with its value everywhere.",
        "tag": "Heatmap visualization tag (0–15).",
        "bool": "Bit-packed boolean flag (0 or 1), stored in r8.",
        "if": "Conditional branch. Condition can use `:=` (walrus) to bind + test.",
        "while": "Loop while condition is true.",
        "loop": "Infinite loop — use `break` to exit.",
        "match": "Match expression against `case` values.",
        "break": "Exit the innermost `while` or `loop`.",
        "continue": "Skip to next iteration of the innermost loop.",
        "import": "Load a package by relative path. Use `using` to access exports.",
        "using": "Bring a package's exports into unqualified scope.",
        "package": "Declare this file's package name.",
        "export": "Make a `func` or `const` visible to importers.",
        "extern": "Declare an optional register — removed if not bound by importer.",
        "action": "Marks a function as tick-consuming (move/pickup/drop).",
        "local": "Compiler-assigned temporary register.",
        "exit": "Declare an exit point in a behavior.",
        "move": "Move in a direction. Consumes a tick.",
        "pickup": "Pick up food at current cell. Consumes a tick.",
        "drop": "Drop carried food at current cell. Consumes a tick.",
    }
    if word in KEYWORD_DOCS:
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=f"**{word}** — {KEYWORD_DOCS[word]}",
        ))

    return None


# ── Go to Definition ─────────────────────────────────────────────

@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
def definition(params: lsp.DefinitionParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    lines = doc.source.split("\n")
    if params.position.line >= len(lines):
        return None
    line = lines[params.position.line]
    sd = _source_dir(params.text_document.uri)

    # Skip if cursor is in a comment (but allow strings for import paths)
    cs_ranges = _compute_comment_string_ranges(doc.source)
    col = params.position.character
    for sl, sc, el, ec in cs_ranges:
        is_comment = False
        src_line = lines[sl] if sl < len(lines) else ""
        if sc < len(src_line) and src_line[sc:sc+2] == "//":
            is_comment = True
        elif sc + 1 < len(src_line) and src_line[sc:sc+2] == "/*":
            is_comment = True
        if is_comment:
            if sl == el and params.position.line == sl and sc <= col < ec:
                return None
            if sl != el:
                if params.position.line == sl and col >= sc:
                    return None
                if sl < params.position.line < el:
                    return None
                if params.position.line == el and col < ec:
                    return None

    # Cmd+click on import path string → open the package directory/file
    import_match = re.match(r'\s*import\s+"([^"]+)"', line)
    if import_match:
        imp_path = import_match.group(1)
        col = params.position.character
        str_start = line.index(f'"{imp_path}"')
        str_end = str_start + len(imp_path) + 2
        if str_start <= col <= str_end:
            resolved = _find_module(imp_path, sd)
            if resolved:
                if resolved.is_dir():
                    sw_files = sorted(resolved.glob("*.sw"))
                    if sw_files:
                        return lsp.Location(
                            uri=f"file://{sw_files[0]}",
                            range=lsp.Range(
                                start=lsp.Position(line=0, character=0),
                                end=lsp.Position(line=0, character=0),
                            ),
                        )
                else:
                    return lsp.Location(
                        uri=f"file://{resolved}",
                        range=lsp.Range(
                            start=lsp.Position(line=0, character=0),
                            end=lsp.Position(line=0, character=0),
                        ),
                    )
            return None

    # Cmd+click on `using <name>` → open the package
    using_match = re.match(r'\s*using\s+(\w+)', line)
    if using_match:
        pkg_name = using_match.group(1)
        col = params.position.character
        name_start = using_match.start(1)
        name_end = using_match.end(1)
        if name_start <= col <= name_end:
            symbols = _collect_symbols(doc.source, sd)
            if pkg_name in symbols.get("import_paths", {}):
                resolved = symbols["import_paths"][pkg_name]
                if resolved.is_dir():
                    sw_files = sorted(resolved.glob("*.sw"))
                    if sw_files:
                        return lsp.Location(
                            uri=f"file://{sw_files[0]}",
                            range=lsp.Range(
                                start=lsp.Position(line=0, character=0),
                                end=lsp.Position(line=0, character=0),
                            ),
                        )
                else:
                    return lsp.Location(
                        uri=f"file://{resolved}",
                        range=lsp.Range(
                            start=lsp.Position(line=0, character=0),
                            end=lsp.Position(line=0, character=0),
                        ),
                    )

    # Check for qualified name: cursor on pkg.member
    qual_match = re.search(r'(\w+)\.(\w+)', line)
    col = params.position.character
    if qual_match and qual_match.start() <= col <= qual_match.end():
        pkg = qual_match.group(1)
        member = qual_match.group(2)
        # Navigate to the member's definition in the package
        symbols = _collect_symbols(doc.source, sd)
        if pkg in symbols.get("import_paths", {}):
            resolved = symbols["import_paths"][pkg]
            sw_files = sorted(resolved.glob("*.sw")) if resolved.is_dir() else [resolved]
            for sw_file in sw_files:
                mod_src = sw_file.read_text()
                loc = _find_definition(mod_src, member)
                if loc:
                    ln, c = loc
                    return lsp.Location(
                        uri=f"file://{sw_file}",
                        range=lsp.Range(
                            start=lsp.Position(line=ln, character=c),
                            end=lsp.Position(line=ln, character=c + len(member)),
                        ),
                    )
        return None

    word = _word_at(line, params.position.character)
    if not word:
        return None

    # Local definition
    loc = _find_definition(doc.source, word)
    if loc:
        line_num, col = loc
        return lsp.Location(
            uri=params.text_document.uri,
            range=lsp.Range(
                start=lsp.Position(line=line_num, character=col),
                end=lsp.Position(line=line_num, character=col + len(word)),
            ),
        )

    # Search imported packages
    symbols = _collect_symbols(doc.source, sd)
    for imp in symbols["imports"]:
        resolved = _find_module(imp, sd)
        if not resolved:
            continue
        sw_files = sorted(resolved.glob("*.sw")) if resolved.is_dir() else [resolved]
        for sw_file in sw_files:
            mod_src = sw_file.read_text()
            loc = _find_definition(mod_src, word)
            if loc:
                line_num, col = loc
                return lsp.Location(
                    uri=f"file://{sw_file}",
                    range=lsp.Range(
                        start=lsp.Position(line=line_num, character=col),
                        end=lsp.Position(line=line_num, character=col + len(word)),
                    ),
                )
    return None


# ── Find References ──────────────────────────────────────────────

def _find_enclosing_func(lines: list[str], line_idx: int) -> tuple[int, int] | None:
    """If line_idx is inside a function definition, return (start, end) line range."""
    for start in range(line_idx, -1, -1):
        if re.match(r'\s*(?:export\s+)?(?:action\s+)?func\s+\w+', lines[start]):
            depth = 0
            for i in range(start, len(lines)):
                depth += lines[i].count("{") - lines[i].count("}")
                if depth <= 0 and "{" in "".join(lines[start:i+1]):
                    return (start, i)
            return (start, len(lines) - 1)
    return None


def _is_func_param(lines: list[str], line_idx: int, word: str) -> tuple[int, int] | None:
    """If word is a parameter of the function at line_idx, return the function's (start, end)."""
    func_range = _find_enclosing_func(lines, line_idx)
    if not func_range:
        return None
    func_line = lines[func_range[0]]
    m = re.search(r'func\s+\w+\s*\(([^)]*)\)', func_line)
    if m:
        params = [p.strip() for p in m.group(1).split(",")]
        if word in params:
            return func_range
    return None


@server.feature(lsp.TEXT_DOCUMENT_REFERENCES)
def references(params: lsp.ReferenceParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    lines = doc.source.split("\n")
    if params.position.line >= len(lines):
        return None

    line = lines[params.position.line]
    col = params.position.character

    # Skip if cursor is in a comment or string
    cs_ranges = _compute_comment_string_ranges(doc.source)
    if _in_comment_or_string(params.position.line, col, cs_ranges):
        return None

    word = _word_at(line, col)
    if not word:
        return None

    esc = re.escape(word)
    pat = re.compile(rf'\b{esc}\b')

    # If word is a function parameter, scope references to that function
    func_scope = _is_func_param(lines, params.position.line, word)
    if func_scope:
        results = []
        start, end = func_scope
        for i in range(start, end + 1):
            for m in pat.finditer(lines[i]):
                if not _in_comment_or_string(i, m.start(), cs_ranges):
                    results.append(lsp.Location(
                        uri=params.text_document.uri,
                        range=lsp.Range(
                            start=lsp.Position(line=i, character=m.start()),
                            end=lsp.Position(line=i, character=m.end()),
                        ),
                    ))
        return results if results else None

    results = []

    # Find in current file
    for i, line_text in enumerate(lines):
        for m in pat.finditer(line_text):
            if not _in_comment_or_string(i, m.start(), cs_ranges):
                results.append(lsp.Location(
                    uri=params.text_document.uri,
                    range=lsp.Range(
                        start=lsp.Position(line=i, character=m.start()),
                        end=lsp.Position(line=i, character=m.end()),
                    ),
                ))

    # Find in imported package files
    sd = _source_dir(params.text_document.uri)
    symbols = _collect_symbols(doc.source, sd)
    for imp in symbols["imports"]:
        resolved = _find_module(imp, sd)
        if not resolved:
            continue
        sw_files = sorted(resolved.glob("*.sw")) if resolved.is_dir() else [resolved]
        for sw_file in sw_files:
            mod_src = sw_file.read_text()
            mod_lines = mod_src.split("\n")
            mod_cs = _compute_comment_string_ranges(mod_src)
            for i, lt in enumerate(mod_lines):
                for m in pat.finditer(lt):
                    if not _in_comment_or_string(i, m.start(), mod_cs):
                        results.append(lsp.Location(
                            uri=f"file://{sw_file}",
                            range=lsp.Range(
                                start=lsp.Position(line=i, character=m.start()),
                                end=lsp.Position(line=i, character=m.end()),
                            ),
                        ))

    return results if results else None


# ── Document Symbols (Outline) ───────────────────────────────────

@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbols(params: lsp.DocumentSymbolParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    lines = doc.source.split("\n")
    symbols = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # States
        m = re.match(r'\bstate\s+(\w+)', stripped)
        if m:
            name = m.group(1)
            end = _find_block_end(lines, i)
            symbols.append(lsp.DocumentSymbol(
                name=name,
                kind=lsp.SymbolKind.Class,
                range=_line_range(i, end),
                selection_range=_word_range(i, line, m.start(1), name),
                detail="state",
            ))

        # Behaviors
        m = re.match(r'\bbehavior\s+(\w+)', stripped)
        if m:
            name = m.group(1)
            end = _find_block_end(lines, i)
            symbols.append(lsp.DocumentSymbol(
                name=name,
                kind=lsp.SymbolKind.Class,
                range=_line_range(i, end),
                selection_range=_word_range(i, line, line.index(name), name),
                detail="behavior",
            ))

        # Init
        if stripped.startswith("init"):
            end = _find_block_end(lines, i)
            symbols.append(lsp.DocumentSymbol(
                name="init",
                kind=lsp.SymbolKind.Constructor,
                range=_line_range(i, end),
                selection_range=_word_range(i, line, line.index("init"), "init"),
            ))

        # Functions
        m = re.match(r'(?:export\s+)?(?:action\s+)?func\s+(\w+)', stripped)
        if m:
            name = m.group(1)
            end = _find_block_end(lines, i)
            symbols.append(lsp.DocumentSymbol(
                name=name,
                kind=lsp.SymbolKind.Function,
                range=_line_range(i, end),
                selection_range=_word_range(i, line, line.index(name), name),
                detail="func",
            ))

        # Constants
        m = re.match(r'(?:export\s+)?const\s+(\w+)\s*=\s*(.*)', stripped)
        if m:
            name, value = m.group(1), m.group(2).strip()
            symbols.append(lsp.DocumentSymbol(
                name=name,
                kind=lsp.SymbolKind.Constant,
                range=_line_range(i, i),
                selection_range=_word_range(i, line, line.index(name), name),
                detail=f"= {value}",
            ))

        # Register declarations
        m = re.match(r'\bregister\b', stripped)
        if m:
            end = i
            if "{" not in line:
                pass
            else:
                end = _find_block_end(lines, i)
            reg_text = "\n".join(lines[i:end+1])
            for rm in re.finditer(r'(\w+)(?:\([^)]*\))?', reg_text):
                rname = rm.group(1)
                if rname in ("register",):
                    continue
                symbols.append(lsp.DocumentSymbol(
                    name=rname,
                    kind=lsp.SymbolKind.Variable,
                    range=_line_range(i, end),
                    selection_range=_word_range(i, line, 0, rname),
                    detail="register",
                ))

    return symbols


def _find_block_end(lines: list[str], start: int) -> int:
    depth = 0
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth <= 0 and "{" in "".join(lines[start:i+1]):
            return i
    return len(lines) - 1


def _line_range(start: int, end: int) -> lsp.Range:
    return lsp.Range(
        start=lsp.Position(line=start, character=0),
        end=lsp.Position(line=end, character=1000),
    )


def _word_range(line: int, text: str, offset: int, word: str) -> lsp.Range:
    return lsp.Range(
        start=lsp.Position(line=line, character=offset),
        end=lsp.Position(line=line, character=offset + len(word)),
    )


# ── Formatting ───────────────────────────────────────────────────

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
