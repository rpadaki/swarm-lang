"""Optimization passes for Swarm antssembly output."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import OptConfig

_LABEL_RE = re.compile(r"^(\w+):$")
_JMP_RE = re.compile(r"^\s+JMP\s+(\S+)")
_JUMP_RE = re.compile(r"^\s+J\w+\s+.*\s+(\S+)$")
_SET_RE = re.compile(r"^\s+SET\s+(\S+)\s+(\S+)$")
_ARITH_RE = re.compile(r"^\s+(\w+)\s+(\S+)\s+(\S+)$")
_ARITH_OPS = {"ADD", "SUB", "MUL", "DIV", "MOD", "AND", "OR", "XOR", "LSHIFT", "RSHIFT"}


def dce(lines: list[str], opt: OptConfig | None = None) -> list[str]:
    """Run post-emission optimization passes on antssembly output."""
    if opt is None:
        from . import OPT_ALL
        opt = OPT_ALL
    prev = None
    while lines != prev:
        prev = lines
        if opt.dead_code:
            jump_targets = _collect_jump_targets(lines)
            lines = _remove_dead_after_jmp(lines, jump_targets)
        if opt.jmp_chain:
            lines = _collapse_jmp_chains(lines)
        if opt.jmp_to_next:
            lines = _remove_jmp_to_next(lines)
        lines = _remove_duplicate_labels(lines)
        if opt.unreferenced_labels:
            lines = _remove_unreferenced_labels(lines)
    if opt.noop_sets:
        lines = _remove_noop_sets(lines)
    if opt.set_op_fusion:
        lines = _fuse_set_op(lines)
    return lines


def _collect_jump_targets(lines: list[str]) -> set[str]:
    """Collect all labels that are targets of jump instructions."""
    targets = set()
    for line in lines:
        m = _JMP_RE.match(line)
        if m:
            targets.add(m.group(1))
        else:
            m = _JUMP_RE.match(line)
            if m:
                targets.add(m.group(1))
    return targets


def _remove_dead_after_jmp(lines: list[str], jump_targets: set[str]) -> list[str]:
    """Remove instructions after unconditional JMP that aren't jump targets."""
    result = []
    dead = False
    for line in lines:
        label_m = _LABEL_RE.match(line)
        if label_m:
            if label_m.group(1) in jump_targets or not dead:
                dead = False
                result.append(line)
            # else: unreferenced label in dead zone — skip it, stay dead
            continue

        if dead:
            continue

        result.append(line)
        if _JMP_RE.match(line):
            dead = True

    return result


def _remove_duplicate_labels(lines: list[str]) -> list[str]:
    """Remove consecutive duplicate labels."""
    result = []
    prev_label = None
    for line in lines:
        m = _LABEL_RE.match(line)
        if m:
            label = m.group(1)
            if label == prev_label:
                continue
            prev_label = label
        else:
            prev_label = None
        result.append(line)
    return result


def _collapse_jmp_chains(lines: list[str]) -> list[str]:
    """Rewrite jump targets that point to a label whose only instruction is JMP elsewhere."""
    # Build label -> index map
    label_idx: dict[str, int] = {}
    for i, line in enumerate(lines):
        m = _LABEL_RE.match(line)
        if m:
            label_idx[m.group(1)] = i

    # Build label -> ultimate target map for labels that just JMP
    redirects: dict[str, str] = {}
    for label, idx in label_idx.items():
        # Look at the first instruction after the label
        for j in range(idx + 1, len(lines)):
            nxt = lines[j].strip()
            if not nxt:
                continue
            if _LABEL_RE.match(lines[j]):
                break
            jmp_m = _JMP_RE.match(lines[j])
            if jmp_m:
                redirects[label] = jmp_m.group(1)
            break

    if not redirects:
        return lines

    # Follow chains (A -> B -> C => A -> C), with cycle detection
    def resolve(label):
        visited = set()
        cur = label
        while cur in redirects and cur not in visited:
            visited.add(cur)
            cur = redirects[cur]
        return cur

    final: dict[str, str] = {l: resolve(l) for l in redirects}

    # Rewrite all jump targets
    result = []
    for line in lines:
        m = _JMP_RE.match(line)
        if m and m.group(1) in final:
            result.append(line.replace(m.group(1), final[m.group(1)]))
            continue
        m = _JUMP_RE.match(line)
        if m and m.group(1) in final:
            result.append(line.replace(m.group(1), final[m.group(1)]))
            continue
        result.append(line)
    return result


def _remove_jmp_to_next(lines: list[str]) -> list[str]:
    """Remove JMP instructions where the target is the immediately following label."""
    result = []
    for i, line in enumerate(lines):
        jmp_m = _JMP_RE.match(line)
        if jmp_m:
            target = jmp_m.group(1)
            for j in range(i + 1, len(lines)):
                nxt = lines[j].strip()
                if not nxt:
                    continue
                label_m = _LABEL_RE.match(lines[j])
                if label_m and label_m.group(1) == target:
                    break  # skip this JMP
                else:
                    result.append(line)
                    break
            else:
                result.append(line)
        else:
            result.append(line)
    return result


def _remove_unreferenced_labels(lines: list[str]) -> list[str]:
    """Remove labels not targeted by any jump (preserving 'main' and state labels)."""
    targets = _collect_jump_targets(lines)
    # Also preserve labels that don't start with '__' (user-defined state/init labels)
    result = []
    for line in lines:
        label_m = _LABEL_RE.match(line)
        if label_m:
            name = label_m.group(1)
            if name in targets or not name.startswith("__"):
                result.append(line)
        else:
            result.append(line)
    return result


def _remove_noop_sets(lines: list[str]) -> list[str]:
    """Remove SET instructions where source == destination."""
    result = []
    for line in lines:
        m = _SET_RE.match(line)
        if m and m.group(1) == m.group(2):
            continue
        result.append(line)
    return result


def _fuse_set_op(lines: list[str]) -> list[str]:
    """Fuse SET r0 <val>; OP rN r0 into OP rN <val>, removing the SET.

    Only applies when the SET target is r0 (scratch register) and the
    next instruction uses r0 as its second operand.
    """
    result = []
    skip = False
    for i, line in enumerate(lines):
        if skip:
            skip = False
            continue
        set_m = _SET_RE.match(line)
        if set_m and set_m.group(1) == "r0" and i + 1 < len(lines):
            val = set_m.group(2)
            arith_m = _ARITH_RE.match(lines[i + 1])
            if (arith_m and arith_m.group(1) in _ARITH_OPS
                    and arith_m.group(3) == "r0" and arith_m.group(2) != "r0"):
                op, dst = arith_m.group(1), arith_m.group(2)
                result.append(f"  {op} {dst} {val}")
                skip = True
                continue
        result.append(line)
    return result
