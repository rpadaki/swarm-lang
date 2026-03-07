"""Tests for swarm.linter, focusing on stale-read detection."""

import unittest

from swarm.tokenizer import tokenize
from swarm.parser import Parser
from swarm.compiler import resolve_imports
from swarm.linter import check


from pathlib import Path

LIB_PARENT = Path(__file__).resolve().parent.parent / "lib"


def lint_src(src: str) -> list[str]:
    prog = Parser(tokenize(src)).parse_program()
    prog, _packages, _pkg_externs = resolve_imports(prog, source_dir=LIB_PARENT)
    return check(prog)


def stale_warnings(warnings: list[str]) -> list[str]:
    return [w for w in warnings if "stale read" in w]


HEADER = """\
import "ant"
using ant
register dir, dx, dy, last_dir
"""


class TestStaleReadAfterAction(unittest.TestCase):
    def test_volatile_read_after_action_warns(self):
        src = HEADER + """\
init { become s }
state s {
    dir = sense(FOOD)
    move(RANDOM)
    if dir != 0 { become s }
    become s
}
"""
        warns = stale_warnings(lint_src(src))
        self.assertEqual(len(warns), 1)
        self.assertIn("dir", warns[0])

    def test_volatile_read_before_action_no_warning(self):
        src = HEADER + """\
init { become s }
state s {
    dir = sense(FOOD)
    if dir != 0 { become s }
    move(RANDOM)
    become s
}
"""
        warns = stale_warnings(lint_src(src))
        self.assertEqual(len(warns), 0)

    def test_stable_read_after_action_no_warning(self):
        src = HEADER + """\
init { become s }
state s {
    dir = carrying()
    move(RANDOM)
    if dir != 0 { become s }
    become s
}
"""
        warns = stale_warnings(lint_src(src))
        self.assertEqual(len(warns), 0)

    def test_reassignment_clears_staleness(self):
        src = HEADER + """\
init { become s }
state s {
    dir = sense(FOOD)
    move(RANDOM)
    dir = 3
    if dir != 0 { become s }
    become s
}
"""
        warns = stale_warnings(lint_src(src))
        self.assertEqual(len(warns), 0)

    def test_multiple_volatile_regs_stale(self):
        src = HEADER + """\
init { become s }
state s {
    dir = sense(FOOD)
    dx = smell(CH_RED)
    move(RANDOM)
    if dir != 0 { become s }
    if dx != 0 { become s }
    become s
}
"""
        warns = stale_warnings(lint_src(src))
        self.assertEqual(len(warns), 2)
        names = " ".join(warns)
        self.assertIn("dir", names)
        self.assertIn("dx", names)

    def test_no_action_no_stale(self):
        src = HEADER + """\
init { become s }
state s {
    dir = sense(FOOD)
    dx = smell(CH_RED)
    if dir != 0 { become s }
    if dx != 0 { become s }
    become s
}
"""
        warns = stale_warnings(lint_src(src))
        self.assertEqual(len(warns), 0)

    def test_nonvolatile_assignment_not_stale(self):
        src = HEADER + """\
init { become s }
state s {
    dir = rand(5)
    move(RANDOM)
    if dir != 0 { become s }
    become s
}
"""
        warns = stale_warnings(lint_src(src))
        self.assertEqual(len(warns), 0)

    def test_condition_walrus_volatile(self):
        src = HEADER + """\
init { become s }
state s {
    if dir := sense(FOOD) {
        move(dir)
        become s
    }
    move(RANDOM)
    if dir != 0 { become s }
    become s
}
"""
        warns = stale_warnings(lint_src(src))
        self.assertEqual(len(warns), 1)
        self.assertIn("dir", warns[0])

    def test_reassign_after_action_clears(self):
        src = HEADER + """\
init { become s }
state s {
    dir = smell(CH_RED)
    move(RANDOM)
    dir = sense(FOOD)
    if dir != 0 { become s }
    become s
}
"""
        warns = stale_warnings(lint_src(src))
        self.assertEqual(len(warns), 0)

    def test_action_in_if_branch_warns_after(self):
        src = HEADER + """\
init { become s }
state s {
    dir = sense(FOOD)
    if dx == 0 {
        move(RANDOM)
    }
    if dir != 0 { become s }
    become s
}
"""
        warns = stale_warnings(lint_src(src))
        self.assertEqual(len(warns), 1)
        self.assertIn("dir", warns[0])


class TestExampleNoStaleWarnings(unittest.TestCase):
    def test_pheromone_trail_no_stale_reads(self):
        example = Path(__file__).resolve().parent.parent / "examples" / "pheromone_trail.sw"
        if not example.exists():
            self.skipTest("pheromone_trail.sw not found")
        src = example.read_text()
        prog = Parser(tokenize(src)).parse_program()
        prog, _packages, _pkg_externs = resolve_imports(prog, source_dir=example.parent)
        warns = stale_warnings(check(prog))
        self.assertEqual(len(warns), 0)


if __name__ == "__main__":
    unittest.main()
