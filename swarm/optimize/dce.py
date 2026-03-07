"""Dead code elimination pass for Swarm antssembly output."""

import re

_LABEL_RE = re.compile(r"^(\w+):$")
_JMP_RE = re.compile(r"^\s+JMP\s+(\S+)")
_JUMP_RE = re.compile(r"^\s+J\w+\s+.*\s+(\S+)$")
_SET_RE = re.compile(r"^\s+SET\s+(\S+)\s+(\S+)$")


def dce(lines: list[str]) -> list[str]:
    """Remove dead code from compiled antssembly output.

    Eliminates:
    - Instructions after unconditional JMP that aren't jump targets
    - JMP to the immediately following label
    - Consecutive duplicate labels
    - Labels not targeted by any jump
    - SET instructions where source == destination
    """
    jump_targets = _collect_jump_targets(lines)
    lines = _remove_dead_after_jmp(lines, jump_targets)
    lines = _remove_jmp_to_next(lines)
    lines = _remove_duplicate_labels(lines)
    lines = _remove_unreferenced_labels(lines)
    lines = _remove_noop_sets(lines)
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
