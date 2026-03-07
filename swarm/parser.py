"""Parser for the Swarm language."""

from .ast import *
from .tokenizer import Tok

ACTION_KW = {"move", "pickup", "drop"}
MARK_KW = {"mark", "set_tag"}

PREC = {"|": 1, "^": 2, "&": 3, "<<": 4, ">>": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}


class Parser:
    def __init__(self, toks):
        self.toks = toks; self.pos = 0

    def peek(self):  return self.toks[self.pos] if self.pos < len(self.toks) else None
    def advance(self): t = self.toks[self.pos]; self.pos += 1; return t
    def at(self, tp, val=None):
        t = self.peek()
        return t and t.type == tp and (val is None or t.value == val)
    def match(self, tp, val=None):
        if self.at(tp, val): return self.advance()
        return None
    def expect(self, tp, val=None):
        t = self.advance()
        if t.type != tp or (val is not None and t.value != val):
            raise SyntaxError(f"line {t.line}: expected {tp}({val}), got {t.type}({t.value})")
        return t

    def _read_maybe_qualified(self):
        """Read an IDENT, possibly followed by DOT IDENT for qualified names."""
        name = self.expect("IDENT").value
        if self.match("DOT"):
            member = self.expect("IDENT").value
            return f"{name}.{member}"
        return name

    def _peek_is_qualified_call(self):
        """Check if current position is at a qualified call: IDENT DOT IDENT LPAREN."""
        if (self.pos + 3 < len(self.toks)
                and self.toks[self.pos].type == "IDENT"
                and self.toks[self.pos+1].type == "DOT"
                and self.toks[self.pos+2].type == "IDENT"
                and self.toks[self.pos+3].type == "LPAREN"):
            return True
        return False

    def parse_program(self):
        r = []
        while self.peek(): r.append(self.parse_top())
        return r

    def parse_top(self):
        t = self.peek()
        if t.type == "IDENT":
            if t.value == "package":  return self.parse_package()
            if t.value == "using":    return self.parse_using()
            if t.value == "import":   return self.parse_import()
            if t.value == "export":   return self.parse_export()
            if t.value == "extern":   return self.parse_extern()
            if t.value == "const":    return self.parse_const()
            if t.value == "register": return self.parse_register()
            if t.value == "tag":      return self.parse_tag()
            if t.value == "bool":     return self.parse_bool_decl()
            if t.value == "init":     self.advance(); return InitBlock(self.parse_block())
            if t.value == "state":    return self.parse_state()
            if t.value == "behavior": return self.parse_behavior()
            if t.value == "func":     return self.parse_func()
        raise SyntaxError(f"line {t.line}: unexpected top-level: {t.value}")

    def parse_package(self):
        self.advance()
        name = self.expect("IDENT").value
        return PackageDecl(name)

    def parse_using(self):
        self.advance()
        name = self.expect("IDENT").value
        return UsingDecl(name)

    def parse_import(self):
        t = self.advance()
        path = self.expect("STRING").value[1:-1]
        return Import(path, t.line)

    def parse_export(self):
        self.advance()
        t = self.peek()
        if t.type == "IDENT" and t.value == "action":
            self.advance()
            if not self.at("IDENT", "func"):
                raise SyntaxError(f"line {t.line}: expected 'func' after 'action'")
            f = self.parse_func()
            return ExportFunc(
                f.name, f.params if hasattr(f, 'params') else [],
                f.ret if hasattr(f, 'ret') else None, f.body, True, is_action=True,
                is_volatile=getattr(f, 'is_volatile', False),
                stable_predicate=getattr(f, 'stable_predicate', None),
            )
        if t.type == "IDENT" and t.value == "func":
            f = self.parse_func()
            return ExportFunc(
                f.name, f.params if hasattr(f, 'params') else [],
                f.ret if hasattr(f, 'ret') else None, f.body, True,
                is_volatile=getattr(f, 'is_volatile', False),
                stable_predicate=getattr(f, 'stable_predicate', None),
            )
        if t.type == "IDENT" and t.value == "const":
            c = self.parse_const()
            return ExportConst(c.name, c.value)
        raise SyntaxError(f"line {t.line}: expected 'func', 'action func', or 'const' after 'export'")

    def parse_func(self):
        self.advance()
        name = self.expect("IDENT").value
        self.expect("LPAREN")
        params = []
        if not self.at("RPAREN"):
            params.append(self.expect("IDENT").value)
            while self.match("COMMA"): params.append(self.expect("IDENT").value)
        self.expect("RPAREN")
        ret = None
        is_volatile = False
        stable_predicate = None
        if self.match("ARROW"):
            if self.at("IDENT", "volatile"):
                self.advance()
                is_volatile = True
            ret = self.expect("IDENT").value
            if self.at("IDENT", "stable"):
                self.advance()
                self.expect("LPAREN")
                stable_predicate = self._read_stable_predicate()
                self.expect("RPAREN")
        body = self.parse_block()
        if params or ret:
            return ExportFunc(name, params, ret, body, False,
                              is_volatile=is_volatile, stable_predicate=stable_predicate)
        return FuncDef(name, body)

    def parse_const(self):
        self.advance(); n = self.expect("IDENT").value; self.expect("OP", "="); return Const(n, self.advance().value)

    def parse_register(self):
        self.advance()
        names = []
        bindings = {}
        initializers = {}
        if self.match("LPAREN"):
            while not self.match("RPAREN"):
                name, binding = self._parse_reg_name()
                names.append(name)
                if binding:
                    bindings[name] = binding
                if self.match("OP", "="):
                    initializers[name] = self.parse_expr()
                self.match("COMMA")
        else:
            name, binding = self._parse_reg_name()
            names.append(name)
            if binding:
                bindings[name] = binding
            if self.match("OP", "="):
                initializers[name] = self.parse_expr()
            while self.match("COMMA"):
                name, binding = self._parse_reg_name()
                names.append(name)
                if binding:
                    bindings[name] = binding
                if self.match("OP", "="):
                    initializers[name] = self.parse_expr()
        return RegDecl(names, bindings, initializers)

    def _parse_reg_name(self):
        name = self.expect("IDENT").value
        binding = None
        if self.match("LPAREN"):
            binding = self._read_maybe_qualified()
            self.expect("RPAREN")
        return name, binding

    def parse_extern(self):
        self.advance()
        if not self.at("IDENT", "register"):
            raise SyntaxError(f"line {self.peek().line}: expected 'register' after 'extern'")
        self.advance()
        names = [self.expect("IDENT").value]
        while self.match("COMMA"): names.append(self.expect("IDENT").value)
        return ExternRegDecl(names)

    def parse_tag(self):
        self.advance()
        if self.at("NUMBER"):
            idx = int(self.advance().value)
            return TagDecl(self.expect("IDENT").value, idx)
        return TagDecl(self.expect("IDENT").value)

    def parse_bool_decl(self):
        self.advance()
        names = [self.expect("IDENT").value]
        while self.match("COMMA"): names.append(self.expect("IDENT").value)
        return BoolDecl(names)

    def parse_state(self):
        self.advance()
        name = self.expect("IDENT").value
        if self.match("OP", "="):
            beh = self.expect("IDENT").value
            args = []
            if self.match("LPAREN"):
                args = self.parse_args()
                self.expect("RPAREN")
            self.expect("LBRACE")
            wiring = {}
            while not self.match("RBRACE"):
                exit_name = self.expect("IDENT").value
                self.expect("ARROW")
                target = self.expect("IDENT").value
                wiring[exit_name] = target
            return StateFromBehavior(name, beh, args, wiring)
        return StateBlock(name, self.parse_block())

    def parse_behavior(self):
        self.advance()
        name = self.expect("IDENT").value
        params = []
        if self.match("LPAREN"):
            if not self.at("RPAREN"):
                params.append(self.expect("IDENT").value)
                while self.match("COMMA"): params.append(self.expect("IDENT").value)
            self.expect("RPAREN")
        self.expect("LBRACE")
        exits, body = [], []
        while not self.match("RBRACE"):
            if self.at("IDENT", "exit"):
                self.advance()
                exits.append(self.expect("IDENT").value)
            else:
                body.append(self.parse_stmt())
        return BehaviorDef(name, params, exits, body)

    def _read_stable_predicate(self):
        """Read a raw predicate string from inside stable(...), handling nested parens."""
        depth = 1
        parts = []
        while depth > 0:
            t = self.peek()
            if t is None:
                raise SyntaxError("unexpected EOF in stable predicate")
            if t.type == "LPAREN":
                depth += 1
                parts.append("(")
                self.advance()
            elif t.type == "RPAREN":
                depth -= 1
                if depth == 0:
                    break
                parts.append(")")
                self.advance()
            else:
                parts.append(t.value)
                self.advance()
        raw = " ".join(parts)
        raw = raw.replace("| |", "||").replace("& &", "&&")
        return raw

    def parse_block(self):
        self.expect("LBRACE"); stmts = []
        while not self.match("RBRACE"): stmts.append(self.parse_stmt())
        return stmts

    def _is_action_or_mark_call(self, name):
        bare = name.split(".")[-1] if "." in name else name
        return bare in ACTION_KW or bare in MARK_KW

    def _is_action_call(self, name):
        bare = name.split(".")[-1] if "." in name else name
        return bare in ACTION_KW

    def parse_stmt(self):
        t = self.peek()
        if not t: raise SyntaxError("unexpected EOF")
        if t.type == "IDENT":
            if t.value == "if":       return self.parse_if()
            if t.value == "while":    self.advance(); return WhileStmt(self.parse_condition(), self.parse_block())
            if t.value == "loop":     self.advance(); return LoopStmt(self.parse_block())
            if t.value == "match":    return self.parse_match()
            if t.value == "break":    self.advance(); return Break()
            if t.value == "continue": self.advance(); return Continue()
            if t.value == "become":   self.advance(); return Become(self.expect("IDENT").value)
            if t.value == "asm":      return self.parse_asm()

            if self._peek_is_qualified_call():
                return self._parse_qualified_call_stmt()

            if t.value in ACTION_KW:  return self.parse_action()
            if t.value in MARK_KW:    return self.parse_mark_action()
            if self.pos+1 < len(self.toks) and self.toks[self.pos+1].type == "LPAREN":
                n = self.advance().value; self.expect("LPAREN"); a = self.parse_args(); self.expect("RPAREN")
                return FuncCall(n)
            if self.pos+1 < len(self.toks) and self.toks[self.pos+1].type == "OP":
                nv = self.toks[self.pos+1].value
                if nv == "=" or (len(nv) == 2 and nv[1] == "=" and nv[0] in "+-*/%&|^"):
                    return self.parse_assignment()
        raise SyntaxError(f"line {t.line}: unexpected: {t.value}")

    def _parse_qualified_call_stmt(self):
        """Parse a qualified call statement: pkg.func(args)."""
        ft_line = self.peek().line
        name = self._read_maybe_qualified()
        self.expect("LPAREN"); a = self.parse_args(); self.expect("RPAREN")
        if self._is_action_call(name) or self._is_action_or_mark_call(name):
            return ActionStmt(func=name, args=a, line=ft_line)
        return FuncCall(name)

    def parse_action(self):
        """Parse action: move(dir)"""
        ft = self.advance(); self.expect("LPAREN"); a = self.parse_args(); self.expect("RPAREN")
        return ActionStmt(func=ft.value, args=a, line=ft.line)

    def parse_mark_action(self):
        ft = self.advance(); self.expect("LPAREN"); a = self.parse_args(); self.expect("RPAREN")
        return ActionStmt(func=ft.value, args=a, line=ft.line)

    def parse_asm(self):
        self.advance()
        self.expect("LBRACE")
        tokens = []
        while not self.match("RBRACE"):
            t = self.advance()
            tokens.append(t.value)
        return AsmBlock(tokens)

    def parse_assignment(self):
        n = self.advance().value
        op_tok = self.advance()
        if op_tok.value == "=":
            return Assignment(n, self.parse_expr())
        base_op = op_tok.value[0]
        return Assignment(n, BinExpr(n, base_op, self.parse_expr()))

    def _is_binop(self):
        t = self.peek()
        return t and t.type == "OP" and (t.value in "+-*/%&|^" or t.value in ("<<", ">>"))

    def _parse_atom(self):
        if self.match("LPAREN"):
            expr = self.parse_expr()
            self.expect("RPAREN")
            return expr
        first = self.advance()
        if first.type == "IDENT":
            if self.at("DOT") and self.pos + 1 < len(self.toks) and self.toks[self.pos + 1].type == "IDENT":
                self.advance()
                member = self.advance()
                qname = f"{first.value}.{member.value}"
                if self.at("LPAREN"):
                    self.advance(); a = self.parse_args(); self.expect("RPAREN")
                    return CallExpr(qname, a, first.line)
                return qname
            if self.at("LPAREN"):
                self.advance(); a = self.parse_args(); self.expect("RPAREN")
                return CallExpr(first.value, a, first.line)
        return first.value

    def parse_expr(self, min_prec=0):
        left = self._parse_atom()
        while self._is_binop() and PREC.get(self.peek().value, 0) >= min_prec:
            op = self.advance().value
            right = self.parse_expr(PREC[op] + 1)
            left = BinExpr(left, op, right)
        return left

    def parse_args(self):
        a = []
        if not self.at("RPAREN"):
            a.append(self._read_arg())
            while self.match("COMMA"): a.append(self._read_arg())
        return a

    def _read_arg(self):
        """Read an argument value, supporting qualified names like pkg.CONST."""
        val = self.advance().value
        if self.match("DOT"):
            member = self.advance().value
            return f"{val}.{member}"
        return val

    def parse_condition(self):
        negated = bool(self.match("OP", "!"))
        t = self.peek()
        if (t.type == "IDENT" and self.pos+1 < len(self.toks)
                and self.toks[self.pos+1].type == "OP" and self.toks[self.pos+1].value == ":="):
            name = self.advance().value; self.advance()
            expr = self.parse_expr()
            left = Assignment(name, expr)
            if self.peek() and self.peek().type == "OP" and self.peek().value in ("==","!=",">","<",">=","<="):
                return (left, self.advance().value, self._read_arg())
            return (left, "==" if negated else "!=", "0")
        if t.type == "IDENT":
            if self._peek_is_qualified_call():
                ft_line = t.line
                name = self._read_maybe_qualified()
                self.expect("LPAREN"); a = self.parse_args(); self.expect("RPAREN")
                left = CallExpr(name, a, ft_line)
            elif self.pos+1 < len(self.toks) and self.toks[self.pos+1].type == "LPAREN":
                ft = self.advance(); self.expect("LPAREN"); a = self.parse_args(); self.expect("RPAREN")
                left = CallExpr(ft.value, a, ft.line)
            else:
                left = self._read_arg()
        else:
            left = self.advance().value
        if not self.peek() or self.peek().type != "OP" or self.peek().value not in ("==","!=",">","<",">=","<="):
            return (left, "==" if negated else "!=", "0")
        op = self.advance().value
        right = self._read_arg()
        return (left, op, right)

    def parse_if(self):
        self.advance(); cond = self.parse_condition(); body = self.parse_block()
        eb = None
        if self.match("IDENT", "else"):
            eb = [self.parse_if()] if self.at("IDENT", "if") else self.parse_block()
        return IfStmt(cond, body, eb)

    def parse_match(self):
        self.advance()
        t = self.peek()
        if t.type == "IDENT":
            if self._peek_is_qualified_call():
                ft_line = t.line
                name = self._read_maybe_qualified()
                self.expect("LPAREN"); a = self.parse_args(); self.expect("RPAREN")
                var = CallExpr(name, a, ft_line)
            elif self.pos+1 < len(self.toks) and self.toks[self.pos+1].type == "LPAREN":
                ft = self.advance(); self.expect("LPAREN"); a = self.parse_args(); self.expect("RPAREN")
                var = CallExpr(ft.value, a, ft.line)
            else:
                var = self._read_arg()
        else:
            var = self.advance().value
        self.expect("LBRACE"); cases, default = [], None
        while not self.match("RBRACE"):
            if self.match("IDENT", "case"):
                v = self._read_arg(); cases.append(MatchCase(v, self.parse_block()))
            elif self.match("IDENT", "default"):
                default = self.parse_block()
            else:
                raise SyntaxError(f"line {self.peek().line}: expected case/default")
        return MatchStmt(var, cases, default)
