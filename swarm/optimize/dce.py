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
    - Consecutive duplicate labels
    - SET instructions where source == destination
    """
    jump_targets = _collect_jump_targets(lines)
    lines = _remove_dead_after_jmp(lines, jump_targets)
    lines = _remove_duplicate_labels(lines)
    lines = _remove_noop_sets(lines)
    return lines


def _collect_jump_targets(lines: list[str]) -> set[str]:
    """Collect all labels that are targets of jump instructions."""
    targets = set()
    for line in lines:
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
            label_name = label_m.group(1)
            if label_name in jump_targets or not dead:
                dead = False
                result.append(line)
            else:
                dead = False
                result.append(line)
            continue

        if dead:
            if label_m:
                dead = False
                result.append(line)
            continue

        result.append(line)

        jmp_m = _JMP_RE.match(line)
        if jmp_m:
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


def _remove_noop_sets(lines: list[str]) -> list[str]:
    """Remove SET instructions where source == destination."""
    result = []
    for line in lines:
        m = _SET_RE.match(line)
        if m and m.group(1) == m.group(2):
            continue
        result.append(line)
    return result
