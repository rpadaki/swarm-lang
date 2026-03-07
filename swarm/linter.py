"""
Lint / checker for .sw (Swarm Language) files.

Parses using the compiler's Parser and checks for:
  - Unused registers
  - Unreachable states (not targeted by any transition)
  - Behaviors with unwired exits
  - States with no transitions out (no become in body)

Usage:
    uv run python -m swarm check program.sw
"""

import re
import sys
from pathlib import Path

from .tokenizer import tokenize
from .parser import Parser
from .compiler import Compiler, resolve_imports
from .ast import (
    StateBlock, StateFromBehavior, BehaviorDef, InitBlock, FuncDef, Const,
    RegDecl, TagDecl, BoolDecl, Assignment, ActionStmt, Become, IfStmt, WhileStmt,
    LoopStmt, MatchStmt, FuncCall, RawAsm, BinExpr, CallExpr, Break, Continue,
    ExportFunc, ExportConst, Import, AsmBlock,
)


def _collect_register_names(prog) -> list[str]:
    for node in prog:
        if isinstance(node, RegDecl):
            return node.names
    return []


def _collect_state_names(prog) -> list[str]:
    names = []
    for node in prog:
        if isinstance(node, (StateBlock, StateFromBehavior)):
            names.append(node.name)
    return names


def _collect_behavior_defs(prog) -> dict[str, BehaviorDef]:
    return {n.name: n for n in prog if isinstance(n, BehaviorDef)}


def _collect_func_defs(prog) -> dict[str, FuncDef]:
    return {n.name: n for n in prog if isinstance(n, FuncDef)}


def _refs_in_expr(expr):
    """Yield register name references from an expression."""
    if isinstance(expr, str):
        yield expr
    elif isinstance(expr, BinExpr):
        if isinstance(expr.left, str): yield expr.left
        if isinstance(expr.right, str): yield expr.right
    elif isinstance(expr, CallExpr):
        for a in expr.args:
            if isinstance(a, str): yield a


def _walk_stmts(stmts, func_defs=None):
    """Yield all statements recursively, expanding func calls."""
    for s in stmts:
        yield s
        if isinstance(s, IfStmt):
            yield from _walk_stmts(s.body, func_defs)
            if s.else_body:
                yield from _walk_stmts(s.else_body, func_defs)
        elif isinstance(s, WhileStmt):
            yield from _walk_stmts(s.body, func_defs)
        elif isinstance(s, LoopStmt):
            yield from _walk_stmts(s.body, func_defs)
        elif isinstance(s, MatchStmt):
            for c in s.cases:
                yield from _walk_stmts(c.body, func_defs)
            if s.default_body:
                yield from _walk_stmts(s.default_body, func_defs)
        elif isinstance(s, FuncCall) and func_defs and s.name in func_defs:
            yield from _walk_stmts(func_defs[s.name].body, func_defs)


def _collect_register_usage(stmts, func_defs=None):
    """Return (set of read regs, set of written regs)."""
    read, written = set(), set()
    for s in _walk_stmts(stmts, func_defs):
        if isinstance(s, Assignment):
            written.add(s.target)
            for ref in _refs_in_expr(s.expr):
                read.add(ref)
        elif isinstance(s, ActionStmt):
            for a in s.args:
                if isinstance(a, str): read.add(a)
        elif isinstance(s, IfStmt):
            left, _op, right = s.cond
            if isinstance(left, str):
                read.add(left)
            elif isinstance(left, CallExpr):
                for a in left.args:
                    if isinstance(a, str): read.add(a)
            elif isinstance(left, Assignment):
                written.add(left.target)
                for ref in _refs_in_expr(left.expr):
                    if isinstance(ref, str): read.add(ref)
            if isinstance(right, str):
                read.add(right)
        elif isinstance(s, WhileStmt):
            left, _op, right = s.cond
            if isinstance(left, str):
                read.add(left)
            elif isinstance(left, CallExpr):
                for a in left.args:
                    if isinstance(a, str): read.add(a)
            elif isinstance(left, Assignment):
                written.add(left.target)
                for ref in _refs_in_expr(left.expr):
                    if isinstance(ref, str): read.add(ref)
            if isinstance(right, str):
                read.add(right)
        elif isinstance(s, MatchStmt):
            if isinstance(s.var, str):
                read.add(s.var)
            elif isinstance(s.var, CallExpr):
                for a in s.var.args:
                    read.add(a)
    return read, written


def _collect_transitions(stmts, func_defs=None):
    """Return set of state names this block can transition to."""
    targets = set()
    for s in _walk_stmts(stmts, func_defs):
        if isinstance(s, Become):
            targets.add(s.target)
    return targets


def _has_outgoing_transition(stmts, func_defs=None):
    """True if the statement list has at least one become statement."""
    for s in _walk_stmts(stmts, func_defs):
        if isinstance(s, Become):
            return True
    return False


def check(prog):
    warnings = []
    reg_names = _collect_register_names(prog)
    state_names = _collect_state_names(prog)
    behaviors = _collect_behavior_defs(prog)
    func_defs = _collect_func_defs(prog)

    # Gather all statement bodies for register usage analysis
    all_stmts = []
    for node in prog:
        if isinstance(node, InitBlock):
            all_stmts.extend(node.body)
        elif isinstance(node, StateBlock):
            all_stmts.extend(node.body)
        elif isinstance(node, StateFromBehavior):
            beh = behaviors.get(node.behavior)
            if beh:
                all_stmts.extend(beh.body)

    read_regs, written_regs = _collect_register_usage(all_stmts, func_defs)
    used_regs = read_regs | written_regs

    # Registers used implicitly by the compiler's state dispatch mechanism
    implicit = {"next_st", "next_state", "next"}

    for rname in reg_names:
        if rname not in used_regs and rname not in implicit:
            warnings.append(f"unused register: '{rname}'")

    # Undeclared identifiers
    consts = {n.name for n in prog if isinstance(n, Const)}
    consts |= {n.name for n in prog if isinstance(n, ExportConst)}
    tags = set()
    bools = set()
    efunc_names = set()
    for n in prog:
        if isinstance(n, TagDecl): tags.add(n.name)
        if isinstance(n, BoolDecl): bools.update(n.names)
        if isinstance(n, ExportFunc): efunc_names.add(n.name)
    declared = set(reg_names) | consts | tags | bools | set(state_names) | efunc_names
    for ref in read_regs | written_regs:
        if ref not in declared and not re.match(r'^-?\d+$', ref):
            warnings.append(f"undeclared identifier: '{ref}'")

    # Unreachable states: states not targeted by any transition from init or other states
    all_transitions = set()
    for node in prog:
        if isinstance(node, InitBlock):
            all_transitions |= _collect_transitions(node.body, func_defs)
        elif isinstance(node, StateBlock):
            all_transitions |= _collect_transitions(node.body, func_defs)
        elif isinstance(node, StateFromBehavior):
            beh = behaviors.get(node.behavior)
            if beh:
                # Expand wiring to find real targets
                expanded_targets = set()
                raw_targets = _collect_transitions(beh.body, func_defs)
                for t in raw_targets:
                    if t == "self":
                        expanded_targets.add(node.name)
                    elif t in node.wiring:
                        expanded_targets.add(node.wiring[t])
                    else:
                        expanded_targets.add(t)
                all_transitions |= expanded_targets

    for sname in state_names:
        if sname not in all_transitions:
            warnings.append(f"unreachable state: '{sname}' (not targeted by any transition)")

    # Behaviors with unwired exits (in StateFromBehavior)
    for node in prog:
        if isinstance(node, StateFromBehavior):
            beh = behaviors.get(node.behavior)
            if beh:
                missing = set(beh.exits) - set(node.wiring)
                if missing:
                    warnings.append(
                        f"state '{node.name}': unwired exits from behavior "
                        f"'{node.behavior}': {', '.join(sorted(missing))}"
                    )

    # States with no transitions out
    for node in prog:
        if isinstance(node, StateBlock):
            if not _has_outgoing_transition(node.body, func_defs):
                warnings.append(f"state '{node.name}' has no outgoing transitions")

    return warnings


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m swarm check <file.sw>", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    src = path.read_text()
    prog = Parser(tokenize(src)).parse_program()
    prog, _packages = resolve_imports(prog, source_dir=path.parent)
    warns = check(prog)

    if warns:
        for w in warns:
            print(f"warning: {w}", file=sys.stderr)
        sys.exit(0)
    else:
        print(f"{path}: ok (no warnings)", file=sys.stderr)


if __name__ == "__main__":
    main()
