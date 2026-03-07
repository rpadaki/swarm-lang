"""
Lint / checker for .sw (Swarm Language) files.

Parses using the compiler's Parser and checks for:
  - Unused registers
  - Unreachable states (not targeted by any transition)
  - Behaviors with unwired exits
  - States with no transitions out (no become in body)
  - Stale reads (volatile-derived values used after a tick-consuming action)

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
    LoopStmt, MatchStmt, FuncCall, BinExpr, CallExpr, Break, Continue,
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


def _collect_efunc_map(prog) -> dict[str, ExportFunc]:
    return {n.name: n for n in prog if isinstance(n, ExportFunc)}


def _refs_in_cond(cond):
    """Yield register name references read in a condition tuple."""
    left, _op, right = cond
    if isinstance(left, str):
        yield left
    elif isinstance(left, CallExpr):
        for a in left.args:
            if isinstance(a, str):
                yield a
    elif isinstance(left, Assignment):
        yield from _refs_in_expr(left.expr)
    if isinstance(right, str):
        yield right


def _cond_assigns(cond):
    """Return the target register if the condition contains an assignment (`:=`), else None."""
    left, _op, _right = cond
    if isinstance(left, Assignment):
        return left.target
    return None


def _cond_call_expr(cond):
    """Return the CallExpr from a condition's LHS, if any."""
    left, _op, _right = cond
    if isinstance(left, Assignment) and isinstance(left.expr, CallExpr):
        return left.expr
    if isinstance(left, CallExpr):
        return left
    return None


def _is_volatile_call(call_expr, efunc_map):
    """Return True if a CallExpr invokes a volatile ExportFunc."""
    if not isinstance(call_expr, CallExpr):
        return False
    ef = efunc_map.get(call_expr.func)
    return ef is not None and ef.is_volatile


def _is_action_stmt(stmt, efunc_map):
    """Return True if an ActionStmt invokes an action ExportFunc."""
    if not isinstance(stmt, ActionStmt):
        return False
    ef = efunc_map.get(stmt.func)
    return ef is not None and ef.is_action


def _check_stale_reads_block(stmts, efunc_map, func_defs, volatile, stale):
    """Walk a block of statements, tracking volatile/stale registers.

    Returns list of (register_name,) for each stale read detected.
    Mutates `volatile` and `stale` sets in place.
    """
    warnings = []

    for s in stmts:
        if isinstance(s, Assignment):
            # Check reads first (RHS may read stale registers)
            for ref in _refs_in_expr(s.expr):
                if ref in stale:
                    warnings.append(ref)
            # Assignment clears staleness and may introduce volatility
            stale.discard(s.target)
            volatile.discard(s.target)
            if isinstance(s.expr, CallExpr) and _is_volatile_call(s.expr, efunc_map):
                volatile.add(s.target)

        elif isinstance(s, ActionStmt):
            # Check reads in action args
            for a in s.args:
                if isinstance(a, str) and a in stale:
                    warnings.append(a)
            # If this is a tick-consuming action, all volatile regs become stale
            if _is_action_stmt(s, efunc_map):
                stale.update(volatile)

        elif isinstance(s, IfStmt):
            # Check reads in condition
            for ref in _refs_in_cond(s.cond):
                if ref in stale:
                    warnings.append(ref)
            # Condition assignment may clear/set volatility
            tgt = _cond_assigns(s.cond)
            if tgt:
                stale.discard(tgt)
                volatile.discard(tgt)
                ce = _cond_call_expr(s.cond)
                if ce and _is_volatile_call(ce, efunc_map):
                    volatile.add(tgt)
            # Recurse into branches (snapshot state, merge conservatively)
            vol_snap, stale_snap = volatile.copy(), stale.copy()
            warnings.extend(_check_stale_reads_block(
                s.body, efunc_map, func_defs, volatile, stale))
            vol_then, stale_then = volatile.copy(), stale.copy()
            volatile.clear(); volatile.update(vol_snap)
            stale.clear(); stale.update(stale_snap)
            if s.else_body:
                warnings.extend(_check_stale_reads_block(
                    s.else_body, efunc_map, func_defs, volatile, stale))
            # Merge: a register is volatile/stale if it is in either branch
            volatile.update(vol_then)
            stale.update(stale_then)

        elif isinstance(s, WhileStmt):
            for ref in _refs_in_cond(s.cond):
                if ref in stale:
                    warnings.append(ref)
            tgt = _cond_assigns(s.cond)
            if tgt:
                stale.discard(tgt)
                volatile.discard(tgt)
                ce = _cond_call_expr(s.cond)
                if ce and _is_volatile_call(ce, efunc_map):
                    volatile.add(tgt)
            warnings.extend(_check_stale_reads_block(
                s.body, efunc_map, func_defs, volatile, stale))

        elif isinstance(s, LoopStmt):
            warnings.extend(_check_stale_reads_block(
                s.body, efunc_map, func_defs, volatile, stale))

        elif isinstance(s, MatchStmt):
            if isinstance(s.var, str) and s.var in stale:
                warnings.append(s.var)
            elif isinstance(s.var, CallExpr):
                for a in s.var.args:
                    if isinstance(a, str) and a in stale:
                        warnings.append(a)
            vol_snap, stale_snap = volatile.copy(), stale.copy()
            for c in s.cases:
                volatile.clear(); volatile.update(vol_snap)
                stale.clear(); stale.update(stale_snap)
                warnings.extend(_check_stale_reads_block(
                    c.body, efunc_map, func_defs, volatile, stale))
                vol_snap.update(volatile)
                stale_snap.update(stale)
            if s.default_body:
                volatile.clear(); volatile.update(vol_snap)
                stale.clear(); stale.update(stale_snap)
                warnings.extend(_check_stale_reads_block(
                    s.default_body, efunc_map, func_defs, volatile, stale))
                vol_snap.update(volatile)
                stale_snap.update(stale)
            volatile.clear(); volatile.update(vol_snap)
            stale.clear(); stale.update(stale_snap)

        elif isinstance(s, FuncCall):
            if func_defs and s.name in func_defs:
                warnings.extend(_check_stale_reads_block(
                    func_defs[s.name].body, efunc_map, func_defs, volatile, stale))

    return warnings


def _check_stale_reads(prog, efunc_map, func_defs, behaviors):
    """Check for stale reads across all states and init blocks."""
    warnings = []
    for node in prog:
        body = None
        if isinstance(node, InitBlock):
            body = node.body
        elif isinstance(node, StateBlock):
            body = node.body
        elif isinstance(node, StateFromBehavior):
            beh = behaviors.get(node.behavior)
            if beh:
                body = beh.body
        if body is None:
            continue
        volatile = set()
        stale = set()
        stale_names = _check_stale_reads_block(body, efunc_map, func_defs, volatile, stale)
        seen = set()
        for name in stale_names:
            key = (getattr(node, 'name', 'init'), name)
            if key not in seen:
                seen.add(key)
                warnings.append(
                    f"stale read of '{name}' after action (value may have changed)"
                )
    return warnings


def check(prog):
    warnings = []
    reg_names = _collect_register_names(prog)
    state_names = _collect_state_names(prog)
    behaviors = _collect_behavior_defs(prog)
    func_defs = _collect_func_defs(prog)
    efunc_map = _collect_efunc_map(prog)

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

    for rname in reg_names:
        if rname not in used_regs:
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

    # Stale reads: volatile-derived values used after an action
    warnings.extend(_check_stale_reads(prog, efunc_map, func_defs, behaviors))

    return warnings


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m swarm check <file.sw>", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    src = path.read_text()
    prog = Parser(tokenize(src)).parse_program()
    prog, _packages, _pkg_externs = resolve_imports(prog, source_dir=path.parent)
    warns = check(prog)

    if warns:
        for w in warns:
            print(f"warning: {w}", file=sys.stderr)
        sys.exit(0)
    else:
        print(f"{path}: ok (no warnings)", file=sys.stderr)


if __name__ == "__main__":
    main()
