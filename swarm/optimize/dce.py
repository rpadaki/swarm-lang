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
        if opt.block_reorder:
            lines = _reorder_blocks(lines)
        if opt.jmp_to_next:
            lines = _remove_jmp_to_next(lines)
        lines = _remove_duplicate_labels(lines)
        if opt.unreferenced_labels:
            lines = _remove_unreferenced_labels(lines)
    if opt.noop_sets:
        lines = _remove_noop_sets(lines)
    if opt.save_promote:
        lines = _promote_save(lines)
    if opt.set_op_fusion:
        lines = _fuse_set_op(lines)
    if opt.cmp_reduce:
        lines = _fold_const_ge_le(lines)
    if opt.call_extract:
        lines = _extract_bmd_subroutine(lines)
        lines = _extract_repeated_sequences(lines)
    return lines


def _collect_jump_targets(lines: list[str]) -> set[str]:
    """Collect all labels that are targets of jump instructions."""
    targets = {"main"}  # implicit entry point, never explicitly jumped to
    for line in lines:
        m = _JMP_RE.match(line)
        if m:
            targets.add(m.group(1))
        else:
            m = _JUMP_RE.match(line)
            if m:
                targets.add(m.group(1))
            else:
                m = _CALL_RE.match(line)
                if m:
                    targets.add(m.group(2))
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
            if jmp_m and not _REG_RE.match(jmp_m.group(1)):
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


def _reorder_blocks(lines: list[str]) -> list[str]:
    """Reorder basic blocks so unconditional JMP targets become fallthroughs.

    Blocks connected by fall-through are grouped into chains.
    Chains are reordered so each chain's terminal JMP target starts
    the next chain, allowing jmp_to_next to eliminate the JMP.
    """
    blocks: list[tuple[str | None, list[str]]] = []
    cur_label: str | None = None
    cur_instrs: list[str] = []

    for line in lines:
        if _LABEL_RE.match(line):
            if cur_label is not None or cur_instrs:
                blocks.append((cur_label, cur_instrs))
            cur_label = line
            cur_instrs = []
        else:
            cur_instrs.append(line)
    if cur_label is not None or cur_instrs:
        blocks.append((cur_label, cur_instrs))

    if len(blocks) <= 1:
        return lines

    def _terminal_jmp(instrs: list[str]) -> str | None:
        for i in range(len(instrs) - 1, -1, -1):
            if not instrs[i].strip():
                continue
            m = _JMP_RE.match(instrs[i])
            return m.group(1) if m else None
        return None

    chains: list[list[int]] = []
    chain: list[int] = []
    for i in range(len(blocks)):
        chain.append(i)
        if _terminal_jmp(blocks[i][1]) is not None:
            chains.append(chain)
            chain = []
    if chain:
        chains.append(chain)

    if len(chains) <= 1:
        return lines

    label_to_chain: dict[str, int] = {}
    for ci, ch in enumerate(chains):
        for bi in ch:
            lbl = blocks[bi][0]
            if lbl:
                m = _LABEL_RE.match(lbl)
                if m:
                    label_to_chain[m.group(1)] = ci

    succ: dict[int, int] = {}
    for ci, ch in enumerate(chains):
        target = _terminal_jmp(blocks[ch[-1]][1])
        if target and target in label_to_chain:
            tci = label_to_chain[target]
            if tci != ci:
                succ[ci] = tci

    pred: dict[int, list[int]] = {}
    for ci, tci in succ.items():
        pred.setdefault(tci, []).append(ci)

    placed: set[int] = set()
    order: list[int] = []

    def place(ci: int) -> None:
        while ci is not None and ci not in placed:
            placed.add(ci)
            order.append(ci)
            ci = succ.get(ci)

    def find_root(ci: int) -> int:
        root = ci
        while True:
            preds = [p for p in pred.get(root, []) if p not in placed]
            if preds:
                root = preds[0]
            else:
                return root

    place(find_root(0))
    for ci in range(len(chains)):
        if ci not in placed:
            place(find_root(ci))

    if order == list(range(len(chains))):
        return lines

    result: list[str] = []
    for ci in order:
        for bi in chains[ci]:
            label, instrs = blocks[bi]
            if label:
                result.append(label)
            result.extend(instrs)
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


_REG_RE = re.compile(r"^r[0-7]$")


def _promote_save(lines: list[str]) -> list[str]:
    """Eliminate SET rB rA by computing the preceding chain directly into rB.

    When: <ops computing into rA>; SET rB rA; SET rA <new>
    Becomes: <ops computing into rB>; SET rA <new>
    """
    result = list(lines)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(result) - 1:
            save_m = _SET_RE.match(result[i])
            if not save_m:
                i += 1
                continue
            rB, rA = save_m.group(1), save_m.group(2)
            if not (_REG_RE.match(rA) and _REG_RE.match(rB)) or rA == rB:
                i += 1
                continue
            next_m = _SET_RE.match(result[i + 1])
            if not (next_m and next_m.group(1) == rA):
                i += 1
                continue
            chain_start = None
            for j in range(i - 1, -1, -1):
                line = result[j]
                if not line.strip():
                    continue
                if _LABEL_RE.match(line):
                    break
                s_m = _SET_RE.match(line)
                if s_m:
                    if s_m.group(1) == rA:
                        if s_m.group(2) != rB:
                            chain_start = j
                    break
                a_m = _ARITH_RE.match(line)
                if a_m and a_m.group(1) in _ARITH_OPS and a_m.group(2) == rA:
                    if a_m.group(3) == rB:
                        break
                    continue
                break
            if chain_start is not None:
                for j in range(chain_start, i):
                    if result[j].strip():
                        result[j] = result[j].replace(rA, rB, 1)
                result.pop(i)
                changed = True
                continue
            i += 1
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


_COND_JMP_RE = re.compile(r"^\s+(JGT|JLT)\s+(\S+)\s+(\S+)\s+(\S+)$")
_CALL_RE = re.compile(r"^\s+CALL\s+(\S+)\s+(\S+)$")


def _fold_const_ge_le(lines: list[str]) -> list[str]:
    """Fold SET rX C; J(GT|LT) rY rX L; JEQ rY rX L into a single J(GT|LT) rY adj L.

    When rX is set to a compile-time constant C immediately before a
    two-instruction >= or <= comparison, and rX is immediately overwritten
    after the branch pair, replace all three instructions with one:
      JGT rY rX L  (>= C)  ->  JGT rY (C-1) L
      JLT rY rX L  (<= C)  ->  JLT rY (C+1) L
    The SET is dead and eliminated along with the redundant JEQ.
    """
    result = list(lines)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(result) - 3:
            set_m = _SET_RE.match(result[i])
            if not set_m:
                i += 1
                continue
            rx, const_s = set_m.group(1), set_m.group(2)
            if not (_REG_RE.match(rx) and const_s.lstrip("-").isdigit()):
                i += 1
                continue
            cj_m = _COND_JMP_RE.match(result[i + 1])
            if not (cj_m and cj_m.group(3) == rx):
                i += 1
                continue
            jop, ry, lbl = cj_m.group(1), cj_m.group(2), cj_m.group(4)
            jeq_m2 = re.match(r"^\s+JEQ\s+(\S+)\s+(\S+)\s+(\S+)$", result[i + 2])
            if not (jeq_m2 and jeq_m2.group(1) == ry and jeq_m2.group(2) == rx and jeq_m2.group(3) == lbl):
                i += 1
                continue
            # Verify rX is immediately overwritten so the SET is dead
            next_set_m = _SET_RE.match(result[i + 3])
            if not (next_set_m and next_set_m.group(1) == rx):
                i += 1
                continue
            # Fold: adjust constant and emit single conditional jump
            c = int(const_s)
            adj = str(c - 1) if jop == "JGT" else str(c + 1)
            result[i] = f"  {jop} {ry} {adj} {lbl}"
            del result[i + 1]  # remove original J(GT|LT) rY rX L
            del result[i + 1]  # remove JEQ rY rX L
            changed = True
        i += 1
    return result


def _find_bmd_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Find all occurrences of the 4-direction minimum-pheromone scan block.

    Returns list of (start_idx, end_idx) pairs where start is the index of the
    first instruction (SNIFF 1 r2 r3) and end is exclusive past the final label.
    """
    results = []

    def try_match(start: int) -> int | None:
        """Return exclusive end index if block matches at start, else None."""
        labels: dict[str, str] = {}
        i = start

        def exact(text: str) -> bool:
            nonlocal i
            if i >= len(lines) or lines[i].rstrip() != text:
                return False
            i += 1
            return True

        def jmp(opcode: str, *operands: str, role: str) -> bool:
            nonlocal i
            if i >= len(lines):
                return False
            pat = r"^\s+" + opcode + r"\s+" + r"\s+".join(re.escape(o) for o in operands) + r"\s+(\w+)$"
            m = re.match(pat, lines[i])
            if not m:
                return False
            lbl = m.group(1)
            if role in labels and labels[role] != lbl:
                return False
            labels[role] = lbl
            i += 1
            return True

        def label(role: str) -> bool:
            nonlocal i
            if i >= len(lines):
                return False
            m = _LABEL_RE.match(lines[i])
            if not m:
                return False
            name = m.group(1)
            if role in labels and labels[role] != name:
                return False
            labels[role] = name
            i += 1
            return True

        if not exact("  SNIFF 1 r2 r3"):
            return None
        if not jmp("JLT", "r3", "40", role="skip"):
            return None
        if not exact("  SET r4 255"):
            return None
        if not exact("  SNIFF 1 1 r3"):
            return None
        if not jmp("JGT", "r3", "r4", role="l1"):
            return None
        if not jmp("JEQ", "r3", "r4", role="l1"):
            return None
        if not exact("  SET r4 r3"):
            return None
        if not exact("  SET r2 1"):
            return None
        if not label("l1"):
            return None
        if not exact("  SNIFF 1 2 r3"):
            return None
        if not jmp("JGT", "r3", "r4", role="l2"):
            return None
        if not jmp("JEQ", "r3", "r4", role="l2"):
            return None
        if not exact("  SET r4 r3"):
            return None
        if not exact("  SET r2 2"):
            return None
        if not label("l2"):
            return None
        if not exact("  SNIFF 1 3 r3"):
            return None
        if not jmp("JGT", "r3", "r4", role="l3"):
            return None
        if not jmp("JEQ", "r3", "r4", role="l3"):
            return None
        if not exact("  SET r4 r3"):
            return None
        if not exact("  SET r2 3"):
            return None
        if not label("l3"):
            return None
        if not exact("  SNIFF 1 4 r3"):
            return None
        if not jmp("JGT", "r3", "r4", role="l4"):
            return None
        if not jmp("JEQ", "r3", "r4", role="l4"):
            return None
        if not exact("  SET r2 4"):
            return None
        if not label("l4"):
            return None
        if not label("skip"):
            return None
        return i

    for start in range(len(lines)):
        if lines[start].rstrip() != "  SNIFF 1 r2 r3":
            continue
        end = try_match(start)
        if end is not None:
            results.append((start, end))
    return results


_BMD_SUBROUTINE = [
    "bmd_find:",
    "  SNIFF 1 r2 r3",
    "  JLT r3 40 __bmd_exit",
    "  SET r4 255",
    "  SNIFF 1 1 r3",
    "  JGT r3 r4 __bmd_1",
    "  JEQ r3 r4 __bmd_1",
    "  SET r4 r3",
    "  SET r2 1",
    "__bmd_1:",
    "  SNIFF 1 2 r3",
    "  JGT r3 r4 __bmd_2",
    "  JEQ r3 r4 __bmd_2",
    "  SET r4 r3",
    "  SET r2 2",
    "__bmd_2:",
    "  SNIFF 1 3 r3",
    "  JGT r3 r4 __bmd_3",
    "  JEQ r3 r4 __bmd_3",
    "  SET r4 r3",
    "  SET r2 3",
    "__bmd_3:",
    "  SNIFF 1 4 r3",
    "  JGT r3 r4 __bmd_exit",
    "  JEQ r3 r4 __bmd_exit",
    "  SET r2 4",
    "__bmd_exit:",
    "  JMP r1",
]


def _extract_bmd_subroutine(lines: list[str]) -> list[str]:
    """Extract duplicate 4-direction minimum-pheromone scan blocks into a CALL/RET subroutine.

    Replaces all matching block occurrences (requires >=2) with CALL r1 bmd_find,
    then appends the canonical subroutine. Uses r1 as the link register (safe when
    r1 is dead at every call site through the block's exit).
    """
    blocks = _find_bmd_blocks(lines)
    if len(blocks) < 2:
        return lines

    result = []
    prev = 0
    for start, end in blocks:
        result.extend(lines[prev:start])
        result.append("  CALL r1 bmd_find")
        prev = end
    result.extend(lines[prev:])
    result.extend(_BMD_SUBROUTINE)
    return result


# ---------------------------------------------------------------------------
# General subroutine factoring
# ---------------------------------------------------------------------------

_BRANCH_OPS = {"JMP", "JEQ", "JNE", "JGT", "JLT"}

_sub_counter = 0


def _norm_instr(line: str) -> str | None:
    """Normalize an instruction for sequence matching.

    Replace label targets in branch instructions with '@' so that
    structurally identical sequences with different label names match.
    Returns None for label lines (they are not instructions).
    """
    if _LABEL_RE.match(line):
        return None
    stripped = line.strip()
    if not stripped:
        return None
    parts = stripped.split()
    if not parts:
        return None
    op = parts[0]
    if op in _BRANCH_OPS and len(parts) >= 2:
        # Last token is the label target — normalize it unless it's a register
        last = parts[-1]
        if not _REG_RE.match(last) and not last.lstrip("-").isdigit():
            parts[-1] = "@"
    return " ".join(parts)


def _extract_repeated_sequences(lines: list[str], min_len: int = 5, max_len: int = 80) -> list[str]:
    """Find repeated instruction sequences and extract them into CALL/RET subroutines."""
    global _sub_counter
    _sub_counter = 0
    changed = True
    while changed:
        changed = False
        result = _try_one_extraction(lines, min_len, max_len)
        if result is not None:
            lines = result
            changed = True
    return lines


def _build_label_ref_index(lines: list[str]) -> dict[str, set[int]]:
    """Build a map from label name -> set of line indices that reference it."""
    refs: dict[str, set[int]] = {}
    for i, line in enumerate(lines):
        if _LABEL_RE.match(line):
            continue
        m = _CALL_RE.match(line)
        if m:
            refs.setdefault(m.group(2), set()).add(i)
        m = _JUMP_RE.match(line)
        if m:
            target = m.group(1)
            if not _REG_RE.match(target) and not target.lstrip("-").isdigit():
                refs.setdefault(target, set()).add(i)
        elif _JMP_RE.match(line):
            pass  # already caught by JUMP_RE
    return refs


def _try_one_extraction(lines: list[str], min_len: int, max_len: int) -> list[str] | None:
    """Try to find and extract the single best repeated sequence."""
    global _sub_counter

    instr_indices: list[int] = []
    norm_at: dict[int, str] = {}
    has_call: set[int] = set()
    for i, line in enumerate(lines):
        n = _norm_instr(line)
        if n is not None:
            instr_indices.append(i)
            norm_at[i] = n
            if n.startswith("CALL "):
                has_call.add(len(instr_indices) - 1)

    if len(instr_indices) < min_len * 2:
        return None

    label_refs = _build_label_ref_index(lines)
    norms = [norm_at[instr_indices[p]] for p in range(len(instr_indices))]

    best_savings = 0
    best_extraction = None

    for length in range(min(max_len, len(instr_indices) // 2), min_len - 1, -1):
        windows: dict[tuple[str, ...], list[int]] = {}
        for p in range(len(instr_indices) - length + 1):
            # Quick check: skip if any instruction in window is CALL
            if any((p + k) in has_call for k in range(length)):
                continue
            key = tuple(norms[p + k] for k in range(length))
            windows.setdefault(key, []).append(p)

        for key, positions in windows.items():
            if len(positions) < 2:
                continue

            chosen = []
            last_end = -1
            for p in positions:
                if p >= last_end:
                    chosen.append(p)
                    last_end = p + length
            if len(chosen) < 2:
                continue

            extraction = _validate_and_build(lines, instr_indices, chosen, length, label_refs)
            if extraction is None:
                continue

            new_lines, savings = extraction
            if savings > best_savings:
                best_savings = savings
                best_extraction = new_lines

        if best_extraction is not None:
            return best_extraction

    return best_extraction if best_savings > 0 else None


def _validate_and_build(
    lines: list[str],
    instr_indices: list[int],
    chosen: list[int],
    length: int,
    label_refs: dict[str, set[int]],
) -> tuple[list[str], int] | None:
    """Validate occurrences and build the extraction if valid."""
    global _sub_counter

    count = len(chosen)
    occurrences: list[tuple[int, int]] = []
    for p in chosen:
        start_line = instr_indices[p]
        end_line = instr_indices[p + length - 1] + 1
        occurrences.append((start_line, end_line))

    # Collect internal labels for each occurrence
    all_internal: list[set[str]] = []
    for start, end in occurrences:
        internal: set[str] = set()
        for i in range(start, end):
            m = _LABEL_RE.match(lines[i])
            if m:
                internal.add(m.group(1))
        all_internal.append(internal)

    # Check internal labels aren't referenced from outside any occurrence
    for occ_idx, (start, end) in enumerate(occurrences):
        for lbl in all_internal[occ_idx]:
            refs = label_refs.get(lbl, set())
            for ref_line in refs:
                inside = False
                for os, oe in occurrences:
                    if os <= ref_line < oe:
                        inside = True
                        break
                if not inside:
                    return None

    # For each jump instruction in the sequence, if it targets a non-internal
    # label (an "exit" jump), all occurrences must target the SAME external label.
    # Otherwise the subroutine can't be shared.
    first_internal = all_internal[0]
    for k in range(length):
        line0 = lines[instr_indices[chosen[0] + k]]
        m = _JUMP_RE.match(line0)
        if not m:
            m = _JMP_RE.match(line0)
        if not m:
            continue
        target0 = m.group(1) if not _JMP_RE.match(line0) else _JMP_RE.match(line0).group(1)
        m0 = _JMP_RE.match(line0)
        target0 = m0.group(1) if m0 else None
        if target0 is None:
            m0 = _JUMP_RE.match(line0)
            target0 = m0.group(1) if m0 else None
        if target0 is None or _REG_RE.match(target0) or target0.lstrip("-").isdigit():
            continue
        if target0 in first_internal:
            continue
        # This is an exit jump — verify all occurrences target the same label
        for occ_idx in range(1, len(chosen)):
            line_k = lines[instr_indices[chosen[occ_idx] + k]]
            mk = _JMP_RE.match(line_k)
            target_k = mk.group(1) if mk else None
            if target_k is None:
                mk = _JUMP_RE.match(line_k)
                target_k = mk.group(1) if mk else None
            if target_k != target0:
                return None

    # Check for exit JMP (final instruction is unconditional JMP to label)
    has_exit_jmp = False
    jmp_m = _JMP_RE.match(lines[instr_indices[chosen[0] + length - 1]])
    if jmp_m and not _REG_RE.match(jmp_m.group(1)):
        has_exit_jmp = True

    # Find safe link register
    first_start, first_end = occurrences[0]
    used_regs: set[str] = set()
    for i in range(first_start, first_end):
        for reg in re.findall(r'\br[0-7]\b', lines[i]):
            used_regs.add(reg)

    link_reg = None
    if "r0" not in used_regs:
        link_reg = "r0"
    else:
        for r in range(7, -1, -1):
            rname = f"r{r}"
            if rname in used_regs:
                continue
            safe = True
            for start, _end in occurrences:
                prev_idx = start - 1
                while prev_idx >= 0 and not lines[prev_idx].strip():
                    prev_idx -= 1
                if prev_idx < 0:
                    safe = False
                    break
                prev_m = _SET_RE.match(lines[prev_idx])
                if not (prev_m and prev_m.group(1) == rname):
                    safe = False
                    break
            if safe:
                link_reg = rname
                break

    if link_reg is None:
        return None

    if has_exit_jmp:
        call_cost = 2 * count
        sub_len = length
    else:
        call_cost = count
        sub_len = length + 1

    savings = length * count - (call_cost + sub_len)
    if savings < 2:
        return None

    _sub_counter += 1
    sub_name = f"__sub_{_sub_counter}"

    first_start, first_end = occurrences[0]
    sub_lines_raw = lines[first_start:first_end]

    internal_label_map: dict[str, str] = {}
    label_count = 0
    for line in sub_lines_raw:
        m = _LABEL_RE.match(line)
        if m:
            label_count += 1
            internal_label_map[m.group(1)] = f"__{sub_name}_{label_count}"

    sub_lines: list[str] = [f"{sub_name}:"]
    for line in sub_lines_raw:
        m = _LABEL_RE.match(line)
        if m and m.group(1) in internal_label_map:
            sub_lines.append(f"{internal_label_map[m.group(1)]}:")
            continue
        new_line = line
        for old_lbl, new_lbl in internal_label_map.items():
            new_line = new_line.replace(old_lbl, new_lbl)
        if has_exit_jmp and line is sub_lines_raw[-1]:
            sub_lines.append(f"  JMP {link_reg}")
        else:
            sub_lines.append(new_line)
    if not has_exit_jmp:
        sub_lines.append(f"  JMP {link_reg}")

    result: list[str] = []
    prev = 0
    for occ_idx, (start, end) in enumerate(occurrences):
        result.extend(lines[prev:start])
        result.append(f"  CALL {link_reg} {sub_name}")
        if has_exit_jmp:
            exit_jmp_line = lines[instr_indices[chosen[occ_idx] + length - 1]]
            exit_m = _JMP_RE.match(exit_jmp_line)
            if exit_m:
                result.append(f"  JMP {exit_m.group(1)}")
        prev = end
    result.extend(lines[prev:])
    result.extend(sub_lines)

    return result, savings
