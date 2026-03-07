"""Swarm Language compiler: AST -> Antssembly."""

import copy
from pathlib import Path

from .ast import *
from .tokenizer import tokenize
from .parser import Parser
from .optimize.dce import dce

BINOP = {"+":"ADD","-":"SUB","*":"MUL","/":"DIV","%":"MOD",
         "&":"AND","|":"OR","^":"XOR","<<":"LSHIFT",">>":"RSHIFT"}
COND_JMP = {"==":"JEQ","!=":"JNE",">":"JGT","<":"JLT"}
INV_JMP  = {"JEQ":"JNE","JNE":"JEQ","JGT":"JLT","JLT":"JGT"}



def resolve_imports(prog, source_dir: Path | None = None):
    packages: dict[str, list] = {}
    pkg_externs: dict[str, set[str]] = {}
    resolved = []
    for node in prog:
        if isinstance(node, Import):
            pkg_name, exports, externs = _load_package(node.path, source_dir, node.line)
            if pkg_name:
                packages[pkg_name] = exports
                if externs:
                    pkg_externs[pkg_name] = externs
            else:
                for m in exports:
                    if isinstance(m, ExportFunc):
                        resolved.append(m)
                    elif isinstance(m, ExportConst):
                        resolved.append(Const(m.name, m.value))
        elif isinstance(node, UsingDecl):
            resolved.append(node)
            for m in packages.get(node.name, []):
                if isinstance(m, ExportFunc):
                    resolved.append(m)
                elif isinstance(m, ExportConst):
                    resolved.append(Const(m.name, m.value))
        else:
            resolved.append(node)
    return resolved, packages, pkg_externs


def _load_package(name: str, source_dir: Path | None, line: int):
    """Load a package directory or single file. Returns (pkg_name, exports, externs)."""
    pkg_dir = _find_package_dir(name, source_dir)
    if pkg_dir:
        return _load_package_dir(pkg_dir)
    # Fallback: single file (legacy)
    mod_path = _find_module_file(name, source_dir)
    if mod_path:
        return _load_single_file(mod_path)
    raise SyntaxError(f"line {line}: package not found: '{name}'")


def _find_package_dir(name: str, source_dir: Path | None) -> Path | None:
    if source_dir:
        p = (source_dir / name).resolve()
        if p.is_dir():
            return p
    return None


def _find_module_file(name: str, source_dir: Path | None) -> Path | None:
    if source_dir:
        p = (source_dir / f"{name}.sw").resolve()
        if p.is_file():
            return p
    return None


def _find_module(name: str, source_dir: Path | None) -> Path | None:
    """Find a package directory or single file. Used by LSP."""
    d = _find_package_dir(name, source_dir)
    if d:
        return d
    return _find_module_file(name, source_dir)


def _load_single_file(path: Path):
    """Load exports from a single .sw file."""
    mod_prog = Parser(tokenize(path.read_text())).parse_program()
    pkg_name = None
    exports = []
    externs: set[str] = set()
    for m in mod_prog:
        if isinstance(m, PackageDecl):
            pkg_name = m.name
        elif isinstance(m, ExportFunc):
            exports.append(m)
        elif isinstance(m, ExportConst):
            exports.append(m)
        elif isinstance(m, ExternRegDecl):
            externs.update(m.names)
    return pkg_name, exports, externs


def _load_package_dir(pkg_dir: Path):
    """Load all .sw files in a package directory."""
    pkg_name = None
    exports = []
    externs: set[str] = set()
    for sw_file in sorted(pkg_dir.glob("*.sw")):
        mod_prog = Parser(tokenize(sw_file.read_text())).parse_program()
        for m in mod_prog:
            if isinstance(m, PackageDecl):
                if pkg_name is None:
                    pkg_name = m.name
            elif isinstance(m, ExportFunc):
                exports.append(m)
            elif isinstance(m, ExportConst):
                exports.append(m)
            elif isinstance(m, ExternRegDecl):
                externs.update(m.names)
    return pkg_name, exports, externs


class Compiler:
    def __init__(self, packages: dict | None = None, pkg_externs: dict | None = None):
        self.out: list[str] = []
        self.consts: dict = {}
        self.regs: dict = {}
        self.nreg = 1
        self.lcnt = 0
        self.funcs: dict = {}
        self.efuncs: dict[str, ExportFunc] = {}
        self.states: list[str] = []
        self.sidx: dict = {}
        self.loops: list = []
        self.tags: dict = {}
        self.next_tag = 0
        self.bools: dict[str, tuple[str, int]] = {}
        self.bool_reg: str | None = None
        self.packages: dict[str, list] = packages or {}
        self._pkg_efuncs: dict[str, ExportFunc] = {}
        self._pkg_consts: dict[str, str] = {}
        self._pkg_externs: dict[str, set[str]] = pkg_externs or {}
        self._extern_bindings: dict[str, str] = {}
        self._reg_initializers: list[tuple[str, object]] = []
        self._build_package_index()

    def _build_package_index(self):
        for pkg_name, exports in self.packages.items():
            for m in exports:
                if isinstance(m, ExportFunc):
                    self._pkg_efuncs[f"{pkg_name}.{m.name}"] = m
                elif isinstance(m, ExportConst):
                    self._pkg_consts[f"{pkg_name}.{m.name}"] = m.value

    def _apply_using(self, name):
        """Bring a package's exports (functions and constants) into unqualified scope."""
        exports = self.packages.get(name)
        if not exports:
            return
        for m in exports:
            if isinstance(m, ExportFunc):
                if m.name not in self.efuncs:
                    self.efuncs[m.name] = m
            elif isinstance(m, ExportConst):
                if m.name not in self.consts:
                    self.consts[m.name] = m.value

    def L(self, h="L"):  self.lcnt += 1; return f"__{h}_{self.lcnt}"
    def emit(self, s):    self.out.append(s)
    def emit_lbl(self, s): self.out.append(f"{s}:")

    def R(self, name):
        if name in self.bools:
            raise RuntimeError(f"'{name}' is a bool — use in conditions/assignments, not directly")
        if name in self.regs:      return self.regs[name]
        if name in self.consts:    return self.consts[name]
        if name in self.tags:      return self.tags[name]
        if name in self._pkg_consts: return self._pkg_consts[name]
        return name

    def _resolve_efunc(self, name):
        if name in self.efuncs:
            return self.efuncs[name]
        if name in self._pkg_efuncs:
            return self._pkg_efuncs[name]
        return None

    def _expand_behavior(self, beh, args, wiring, self_name):
        body = copy.deepcopy(beh.body)
        pm = {}
        if beh.params:
            if len(args) != len(beh.params):
                raise RuntimeError(f"behavior '{beh.name}': expected {len(beh.params)} args, got {len(args)}")
            pm = dict(zip(beh.params, args))
        em = {**wiring, "self": self_name}

        def S(val):
            return pm.get(val, val) if isinstance(val, str) else val

        def subst_expr(e):
            if isinstance(e, str): return S(e)
            if isinstance(e, BinExpr):
                if isinstance(e.left, CallExpr): e.left.args = [S(a) for a in e.left.args]
                else: e.left = S(e.left)
                e.right = S(e.right)
            elif isinstance(e, CallExpr):
                e.args = [S(a) for a in e.args]
            return e

        def subst_cond(c):
            left, op, right = c
            if isinstance(left, CallExpr): left.args = [S(a) for a in left.args]
            elif isinstance(left, str): left = S(left)
            return (left, op, S(right))

        def rewrite(stmts):
            for s in stmts:
                if isinstance(s, Become) and s.target in em: s.target = em[s.target]
                if isinstance(s, Assignment):
                    s.target = S(s.target); s.expr = subst_expr(s.expr)
                elif isinstance(s, ActionStmt): s.args = [S(a) for a in s.args]
                elif isinstance(s, IfStmt):
                    s.cond = subst_cond(s.cond); rewrite(s.body)
                    if s.else_body: rewrite(s.else_body)
                elif isinstance(s, WhileStmt):
                    s.cond = subst_cond(s.cond); rewrite(s.body)
                elif isinstance(s, LoopStmt): rewrite(s.body)
                elif isinstance(s, MatchStmt):
                    if isinstance(s.var, str): s.var = S(s.var)
                    elif isinstance(s.var, CallExpr): s.var.args = [S(a) for a in s.var.args]
                    for c in s.cases: rewrite(c.body)
                    if s.default_body: rewrite(s.default_body)
        rewrite(body)
        return body

    def compile(self, prog):
        init = None; states = []; other = []; behaviors = {}
        for s in prog:
            if   isinstance(s, FuncDef):    self.funcs[s.name] = s.body
            elif isinstance(s, ExportFunc): self.efuncs[s.name] = s
            elif isinstance(s, Const):      self.consts[s.name] = s.value
            elif isinstance(s, InitBlock):  init = s
            elif isinstance(s, StateBlock): states.append(s)
            elif isinstance(s, BehaviorDef): behaviors[s.name] = s
            elif isinstance(s, UsingDecl):  self._apply_using(s.name)
            elif isinstance(s, PackageDecl): pass
            elif isinstance(s, ExternRegDecl): pass
            elif isinstance(s, StateFromBehavior):
                beh = behaviors.get(s.behavior)
                if not beh: raise RuntimeError(f"unknown behavior: {s.behavior}")
                missing = set(beh.exits) - set(s.wiring)
                if missing: raise RuntimeError(f"state '{s.name}': unwired exits: {missing}")
                body = self._expand_behavior(beh, s.args, s.wiring, s.name)
                states.append(StateBlock(s.name, body))
            else: other.append(s)

        for sb in states:
            self.sidx[sb.name] = len(self.states)
            self.states.append(sb.name)

        for s in other: self._stmt(s)

        auto_idx = self.next_tag
        for name in self.states:
            if name not in self.tags and auto_idx < 8:
                tag_name = f"_t_{name}"
                self.emit(f".tag {auto_idx} {tag_name}")
                self.tags[name] = str(auto_idx)
                auto_idx += 1

        has_init = init or self._reg_initializers
        if has_init:
            self.emit_lbl("main")
            for name, expr in self._reg_initializers:
                tgt = self.R(name)
                self._compile_expr_into(tgt, expr)
            if init:
                for s in init.body: self._stmt(s)
        for sb in states:
            self.emit_lbl(sb.name)
            if sb.name in self.tags:
                self.emit(f"  TAG {self.tags[sb.name]}")
            for s in sb.body: self._stmt(s)

        self.out = dce(self.out)
        return "\n".join(self.out)

    def _stmt(self, s):
        if   isinstance(s, RegDecl):    self._regdecl(s)
        elif isinstance(s, BoolDecl):   self._booldecl(s)
        elif isinstance(s, TagDecl):    self._tagdecl(s)
        elif isinstance(s, Const):      self.consts[s.name] = s.value
        elif isinstance(s, Assignment): self._assign(s)
        elif isinstance(s, ActionStmt): self._action(s)
        elif isinstance(s, Become):     self.emit(f"  JMP {s.target}")
        elif isinstance(s, IfStmt):     self._if(s)
        elif isinstance(s, WhileStmt):  self._while(s)
        elif isinstance(s, LoopStmt):   self._loop(s)
        elif isinstance(s, MatchStmt):  self._match(s)
        elif isinstance(s, Break):      self.emit(f"  JMP {self.loops[-1][0]}")
        elif isinstance(s, Continue):   self.emit(f"  JMP {self.loops[-1][1]}")
        elif isinstance(s, FuncCall):
            ef = self._resolve_efunc(s.name)
            if ef:
                self._inline_efunc(ef, [], None)
            elif s.name in self.funcs:
                for st in self.funcs[s.name]: self._stmt(st)
            else: raise RuntimeError(f"unknown func: {s.name}")
        elif isinstance(s, AsmBlock):   self._asm_block(s.tokens, {})
        elif isinstance(s, RawAsm):     self.emit(f"  {s.line}")

    def _regdecl(self, s):
        for n in s.names:
            if self.nreg >= 8: raise RuntimeError(f"out of registers for '{n}'")
            r = f"r{self.nreg}"; self.nreg += 1; self.regs[n] = r
            self.emit(f".alias {n} {r}")
        for user_name, extern_qual in s.bindings.items():
            self._extern_bindings[extern_qual] = user_name
        for name, expr in s.initializers.items():
            self._reg_initializers.append((name, expr))

    def _booldecl(self, s):
        if not self.bool_reg:
            if self.nreg >= 8: raise RuntimeError("no register available for bool flags")
            self.bool_reg = f"r{self.nreg}"; self.nreg += 1
            self.emit(f".alias __flags {self.bool_reg}")
        for n in s.names:
            bit = len(self.bools)
            if bit >= 15: raise RuntimeError("too many bools (max 15)")
            self.bools[n] = (self.bool_reg, 1 << bit)

    def _tagdecl(self, s):
        idx = s.index if s.index is not None else self.next_tag
        self.next_tag = idx + 1
        self.emit(f".tag {idx} {s.name}")
        self.tags[s.name] = str(idx)

    def _assign(self, s):
        if s.target in self.bools:
            reg, mask = self.bools[s.target]
            if isinstance(s.expr, str):
                if s.expr in self.bools:
                    sreg, smask = self.bools[s.expr]
                    self.emit(f"  SET r0 {sreg}"); self.emit(f"  AND r0 {smask}")
                    skip = self.L("bs")
                    self.emit(f"  AND {reg} {~mask}"); self.emit(f"  JEQ r0 0 {skip}")
                    self.emit(f"  OR {reg} {mask}"); self.emit_lbl(skip)
                else:
                    val = self.R(s.expr)
                    if val == "0": self.emit(f"  AND {reg} {~mask}")
                    elif val == "1": self.emit(f"  OR {reg} {mask}")
                    else:
                        skip = self.L("bs")
                        self.emit(f"  AND {reg} {~mask}"); self.emit(f"  JEQ {val} 0 {skip}")
                        self.emit(f"  OR {reg} {mask}"); self.emit_lbl(skip)
            elif isinstance(s.expr, CallExpr):
                self._call_expr("r0", s.expr)
                skip = self.L("bs")
                self.emit(f"  AND {reg} {~mask}"); self.emit(f"  JEQ r0 0 {skip}")
                self.emit(f"  OR {reg} {mask}"); self.emit_lbl(skip)
            return
        if isinstance(s.expr, str) and s.expr in self.bools:
            tgt = self.R(s.target)
            reg, mask = self.bools[s.expr]
            self.emit(f"  SET {tgt} {reg}"); self.emit(f"  AND {tgt} {mask}")
            return
        tgt = self.R(s.target)
        self._compile_expr_into(tgt, s.expr)

    def _compile_expr_into(self, tgt, expr):
        if isinstance(expr, str):
            val = self.R(expr)
            if tgt != val: self.emit(f"  SET {tgt} {val}")
        elif isinstance(expr, CallExpr):
            self._call_expr(tgt, expr)
        elif isinstance(expr, BinExpr):
            op = BINOP.get(expr.op)
            self._compile_expr_into(tgt, expr.left)
            if isinstance(expr.right, (BinExpr, CallExpr)):
                self._compile_expr_into("r0", expr.right)
                self.emit(f"  {op} {tgt} r0")
            else:
                self.emit(f"  {op} {tgt} {self.R(expr.right)}")

    def _call_expr(self, tgt, e):
        ef = self._resolve_efunc(e.func)
        if ef and len(e.args) == len(ef.params):
            self._inline_efunc(ef, e.args, tgt)
            return
        if len(e.args) == 2:
            alt = f"{e.func}_range"
            ef_alt = self._resolve_efunc(alt)
            if ef_alt and len(e.args) == len(ef_alt.params):
                self._inline_efunc(ef_alt, e.args, tgt)
                return
        raise RuntimeError(f"line {e.line}: unknown func: {e.func} (did you forget: import \"libant\"?)")

    def _all_externs(self):
        """Return the set of all extern register names across all packages."""
        result = set()
        for names in self._pkg_externs.values():
            result.update(names)
        return result

    def _is_extern_bound(self, name):
        """Check if an extern register name is bound by the user program."""
        for pkg_name, externs in self._pkg_externs.items():
            if name in externs:
                qual = f"{pkg_name}.{name}"
                if qual in self._extern_bindings:
                    return True
        return False

    def _stmt_refs_names(self, s):
        """Collect all identifier names referenced by a statement."""
        names = set()
        if isinstance(s, Assignment):
            names.add(s.target)
            names.update(self._expr_refs_names(s.expr))
        elif isinstance(s, IfStmt):
            names.update(self._cond_refs_names(s.cond))
            for st in s.body:
                names.update(self._stmt_refs_names(st))
            if s.else_body:
                for st in s.else_body:
                    names.update(self._stmt_refs_names(st))
        elif isinstance(s, WhileStmt):
            names.update(self._cond_refs_names(s.cond))
            for st in s.body:
                names.update(self._stmt_refs_names(st))
        elif isinstance(s, LoopStmt):
            for st in s.body:
                names.update(self._stmt_refs_names(st))
        elif isinstance(s, ActionStmt):
            for a in s.args:
                names.add(a)
        elif isinstance(s, FuncCall):
            names.add(s.name)
        elif isinstance(s, AsmBlock):
            names.update(s.tokens)
        elif isinstance(s, MatchStmt):
            names.update(self._expr_refs_names(s.var))
            for c in s.cases:
                for st in c.body:
                    names.update(self._stmt_refs_names(st))
            if s.default_body:
                for st in s.default_body:
                    names.update(self._stmt_refs_names(st))
        return names

    def _expr_refs_names(self, e):
        """Collect all identifier names referenced by an expression."""
        if isinstance(e, str):
            return {e}
        if isinstance(e, BinExpr):
            return self._expr_refs_names(e.left) | self._expr_refs_names(e.right)
        if isinstance(e, CallExpr):
            names = {e.func}
            for a in e.args:
                names.add(a)
            return names
        return set()

    def _cond_refs_names(self, cond):
        left, op, right = cond
        names = set()
        if isinstance(left, str):
            names.add(left)
        elif isinstance(left, CallExpr):
            names.update(self._expr_refs_names(left))
        elif isinstance(left, Assignment):
            names.update(self._stmt_refs_names(left))
        if isinstance(right, str):
            names.add(right)
        return names

    def _stmt_uses_unbound_extern(self, s, all_externs):
        """Check if a statement references any unbound extern register."""
        refs = self._stmt_refs_names(s)
        for name in refs:
            if name in all_externs and not self._is_extern_bound(name):
                return True
        return False

    def _inline_efunc(self, ef, args, tgt):
        if len(args) != len(ef.params):
            raise RuntimeError(f"func '{ef.name}': expected {len(ef.params)} args, got {len(args)}")
        bindings = dict(zip(ef.params, args))
        if ef.ret and tgt:
            bindings[ef.ret] = tgt
        all_externs = self._all_externs()
        for s in ef.body:
            if all_externs and self._stmt_uses_unbound_extern(s, all_externs):
                continue
            if isinstance(s, AsmBlock):
                self._asm_block(s.tokens, bindings)
            else:
                self._inline_stmt(s, bindings, all_externs)

    def _inline_stmt(self, s, bindings, all_externs):
        """Compile a statement from an inlined efunc, applying DCE for unbound externs."""
        if isinstance(s, IfStmt) and all_externs:
            if self._cond_uses_unbound_extern(s.cond, all_externs):
                return
            dce_body = [st for st in s.body if not self._stmt_uses_unbound_extern(st, all_externs)]
            dce_else = None
            if s.else_body:
                dce_else = [st for st in s.else_body if not self._stmt_uses_unbound_extern(st, all_externs)]
            patched = IfStmt(s.cond, dce_body, dce_else)
            self._stmt(patched)
        else:
            self._stmt(s)

    def _cond_uses_unbound_extern(self, cond, all_externs):
        refs = self._cond_refs_names(cond)
        for name in refs:
            if name in all_externs and not self._is_extern_bound(name):
                return True
        return False

    def R_asm(self, tok, bindings):
        if tok in bindings:
            v = bindings[tok]
            if v in self.regs: return self.regs[v]
            if v in self.consts: return self.consts[v]
            if v in self._pkg_consts: return self._pkg_consts[v]
            return v
        if tok in self.regs: return self.regs[tok]
        if tok in self.consts: return self.consts[tok]
        if tok in self._pkg_consts: return self._pkg_consts[tok]
        if tok in self.tags: return self.tags[tok]
        return tok

    def _asm_block(self, tokens, bindings):
        resolved = [self.R_asm(t, bindings) for t in tokens]
        self.emit(f"  {' '.join(resolved)}")

    def _action(self, s):
        ef = self._resolve_efunc(s.func)
        if not ef:
            raise RuntimeError(f"line {s.line}: unknown func: {s.func} (did you forget: import \"libant\"?)")
        self._inline_efunc(ef, s.args, None)

    def _eval_cond(self, cond):
        left, op, right = cond
        if isinstance(left, Assignment):
            self._assign(left)
            tgt = self.R(left.target) if left.target not in self.bools else "r0"
            return tgt, op, self.R(right)
        if isinstance(left, str) and left in self.bools:
            reg, mask = self.bools[left]
            self.emit(f"  SET r0 {reg}"); self.emit(f"  AND r0 {mask}")
            return "r0", op, self.R(right)
        if isinstance(left, CallExpr):
            self._call_expr("r0", left)
            return "r0", op, self.R(right)
        return self.R(left), op, self.R(right)

    def _single_become(self, body):
        return body[0].target if len(body) == 1 and isinstance(body[0], Become) else None

    def _if(self, s):
        l, op, r = self._eval_cond(s.cond)
        j = COND_JMP.get(op)
        if not j: raise RuntimeError(f"bad cond: {op}")

        tgt = self._single_become(s.body)
        if tgt and not s.else_body:
            self.emit(f"  {j} {l} {r} {tgt}"); return
        if tgt and s.else_body:
            et = self._single_become(s.else_body)
            if et: self.emit(f"  {j} {l} {r} {tgt}"); self.emit(f"  JMP {et}"); return

        inv = INV_JMP[j]
        if s.else_body:
            el, end = self.L("else"), self.L("fi")
            self.emit(f"  {inv} {l} {r} {el}")
            if j in ("JGT", "JLT"): self.emit(f"  JEQ {l} {r} {el}")
            for st in s.body: self._stmt(st)
            self.emit(f"  JMP {end}"); self.emit_lbl(el)
            for st in s.else_body: self._stmt(st)
            self.emit_lbl(end)
        else:
            end = self.L("fi")
            self.emit(f"  {inv} {l} {r} {end}")
            if j in ("JGT", "JLT"): self.emit(f"  JEQ {l} {r} {end}")
            for st in s.body: self._stmt(st)
            self.emit_lbl(end)

    def _while(self, s):
        top, brk, body = self.L("wh"), self.L("we"), self.L("wb")
        self.loops.append((brk, top))
        self.emit_lbl(top)
        l, op, r = self._eval_cond(s.cond)
        j = COND_JMP.get(op)
        self.emit(f"  {j} {l} {r} {body}"); self.emit(f"  JMP {brk}")
        self.emit_lbl(body)
        for st in s.body: self._stmt(st)
        self.emit(f"  JMP {top}"); self.emit_lbl(brk)
        self.loops.pop()

    def _loop(self, s):
        top, brk = self.L("lp"), self.L("le")
        self.loops.append((brk, top))
        self.emit_lbl(top)
        for st in s.body: self._stmt(st)
        self.emit(f"  JMP {top}"); self.emit_lbl(brk)
        self.loops.pop()

    def _match(self, s):
        if isinstance(s.var, CallExpr):
            self._call_expr("r0", s.var); var = "r0"
        else:
            var = self.R(s.var)
        end = self.L("em"); cls = []
        for c in s.cases:
            cl = self.L("cs"); cls.append(cl)
            self.emit(f"  JEQ {var} {self.R(c.value)} {cl}")
        dl = None
        if s.default_body: dl = self.L("df"); self.emit(f"  JMP {dl}")
        else: self.emit(f"  JMP {end}")
        for i, c in enumerate(s.cases):
            self.emit_lbl(cls[i])
            for st in c.body: self._stmt(st)
            self.emit(f"  JMP {end}")
        if dl:
            self.emit_lbl(dl)
            for st in s.default_body: self._stmt(st)
        self.emit_lbl(end)
