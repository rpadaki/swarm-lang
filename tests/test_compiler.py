"""Tests for swarm.compiler."""

import unittest
from pathlib import Path

from swarm.tokenizer import tokenize
from swarm.parser import Parser
from swarm.compiler import Compiler, resolve_imports, _find_module, LIB_DIR


def compile_src(src: str) -> str:
    prog = Parser(tokenize(src)).parse_program()
    prog, packages = resolve_imports(prog, source_dir=None)
    return Compiler(packages).compile(prog)


MINIMAL = """\
import "libant"
register dir, mark_str, dx, dy, next_st, last_dir, tmp
init {
    dx = 0
    dy = 0
    become wander
}
state wander {
    move(RANDOM)
    become wander
}
"""


class TestMinimalCompile(unittest.TestCase):
    def test_produces_output(self):
        out = compile_src(MINIMAL)
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_contains_main_label(self):
        out = compile_src(MINIMAL)
        self.assertIn("main:", out)

    def test_contains_state_label(self):
        out = compile_src(MINIMAL)
        self.assertIn("wander:", out)

    def test_contains_move_instruction(self):
        out = compile_src(MINIMAL)
        self.assertIn("MOVE", out)


class TestRegisterAllocation(unittest.TestCase):
    def test_registers_start_at_r1(self):
        out = compile_src(MINIMAL)
        self.assertIn(".alias dir r1", out)

    def test_sequential_allocation(self):
        out = compile_src(MINIMAL)
        lines = out.split("\n")
        aliases = [l.strip() for l in lines if l.strip().startswith(".alias")]
        expected_pairs = [
            ("dir", "r1"), ("mark_str", "r2"), ("dx", "r3"),
            ("dy", "r4"), ("next_st", "r5"), ("last_dir", "r6"), ("tmp", "r7"),
        ]
        for name, reg in expected_pairs:
            self.assertIn(f".alias {name} {reg}", aliases)

    def test_too_many_registers_raises(self):
        src = "register a, b, c, d, e, f, g, h\nstate s { become s }"
        with self.assertRaises(RuntimeError):
            compile_src(src)


class TestResolveImports(unittest.TestCase):
    def test_find_module_libant(self):
        p = _find_module("libant", None)
        self.assertIsNotNone(p)
        self.assertTrue(p.exists())
        self.assertEqual(p.name, "libant.sw")

    def test_resolve_imports_brings_in_exports(self):
        src = 'import "libant"'
        prog = Parser(tokenize(src)).parse_program()
        resolved, _packages = resolve_imports(prog)
        names = [n.name for n in resolved if hasattr(n, "name")]
        self.assertIn("sense", names)
        self.assertIn("probe", names)
        self.assertIn("move", names)

    def test_missing_module_raises(self):
        src = 'import "nonexistent_module"'
        prog = Parser(tokenize(src)).parse_program()
        with self.assertRaises(SyntaxError):
            resolve_imports(prog)


class TestConsts(unittest.TestCase):
    def test_const_substitution(self):
        src = """\
import "libant"
const MY_VAL = 42
register dir, dx, dy, next_st, last_dir
init { dx = MY_VAL become s }
state s { move(RANDOM) become s }
"""
        out = compile_src(src)
        self.assertIn("SET r2 42", out)


class TestConditionCodegen(unittest.TestCase):
    def test_if_become_compiles_to_jeq(self):
        src = """\
import "libant"
register dir, dx, dy, next_st, last_dir
init { dx = 0 become s }
state s {
    if dx == 0 { become s }
    move(RANDOM)
    become s
}
"""
        out = compile_src(src)
        self.assertIn("JEQ", out)


class TestBehaviorExpansion(unittest.TestCase):
    def test_behavior_wiring_compiles(self):
        src = """\
import "libant"
register scratch, dir, dx, dy, next_st, last_dir
behavior wander {
    exit found
    move(RANDOM)
    become self
}
init { dx = 0 dy = 0 become explore }
state explore = wander { found -> explore }
"""
        out = compile_src(src)
        self.assertIn("explore:", out)
        self.assertIn("MOVE", out)


class TestPackageSystem(unittest.TestCase):
    def test_import_detects_package_name(self):
        src = 'import "libant"'
        prog = Parser(tokenize(src)).parse_program()
        _resolved, packages = resolve_imports(prog)
        self.assertIn("ant", packages)

    def test_package_exports_available_qualified(self):
        src = """\
import "libant"
register dir, dx, dy, next_st, last_dir
init { dx = 0 become s }
state s {
    if ant.probe(HERE) == ant.FOOD { become s }
    ant.move(ant.RANDOM)
    become s
}
"""
        out = compile_src(src)
        self.assertIn("PROBE", out)
        self.assertIn("MOVE", out)

    def test_using_brings_names_into_scope(self):
        src = """\
import "libant"
using ant
register dir, dx, dy, next_st, last_dir
init { dx = 0 become s }
state s {
    move(RANDOM)
    become s
}
"""
        out = compile_src(src)
        self.assertIn("MOVE", out)

    def test_action_func_is_action_flag(self):
        src = 'import "libant"'
        prog = Parser(tokenize(src)).parse_program()
        _resolved, packages = resolve_imports(prog)
        ant_exports = packages["ant"]
        move_ef = next(e for e in ant_exports if hasattr(e, 'name') and e.name == "move")
        self.assertTrue(move_ef.is_action)
        sense_ef = next(e for e in ant_exports if hasattr(e, 'name') and e.name == "sense")
        self.assertFalse(sense_ef.is_action)

    def test_contains_post_move(self):
        out = compile_src(MINIMAL)
        self.assertIn("__post_move:", out)

    def test_action_with_arrow_transition(self):
        src = """\
import "libant"
register dir, dx, dy, next_st, last_dir
init { dx = 0 become s }
state s {
    move(RANDOM) -> s
}
"""
        out = compile_src(src)
        self.assertIn("MOVE", out)
        self.assertIn("__post_move", out)


if __name__ == "__main__":
    unittest.main()
