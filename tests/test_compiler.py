"""Tests for swarm.compiler."""

import unittest
from pathlib import Path

from swarm.tokenizer import tokenize
from swarm.parser import Parser
from swarm.compiler import Compiler, resolve_imports, _find_module, LIB_DIR


def compile_src(src: str) -> str:
    prog = Parser(tokenize(src)).parse_program()
    prog, packages, pkg_externs = resolve_imports(prog, source_dir=None)
    return Compiler(packages, pkg_externs).compile(prog)


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
        resolved, _packages, _pkg_externs = resolve_imports(prog)
        names = [n.name for n in resolved if hasattr(n, "name")]
        self.assertIn("sense", names)
        self.assertIn("probe", names)
        self.assertIn("move", names)

    def test_find_module_ant_alias(self):
        p = _find_module("ant", None)
        self.assertIsNotNone(p)
        self.assertTrue(p.exists())
        self.assertEqual(p.name, "libant.sw")

    def test_import_ant_resolves(self):
        src = 'import "ant"'
        prog = Parser(tokenize(src)).parse_program()
        resolved, packages, _pkg_externs = resolve_imports(prog)
        self.assertIn("ant", packages)
        names = [n.name for n in resolved if hasattr(n, "name")]
        self.assertIn("sense", names)
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
        _resolved, packages, _pkg_externs = resolve_imports(prog)
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
        _resolved, packages, _pkg_externs = resolve_imports(prog)
        ant_exports = packages["ant"]
        move_ef = next(e for e in ant_exports if hasattr(e, 'name') and e.name == "move")
        self.assertTrue(move_ef.is_action)
        sense_ef = next(e for e in ant_exports if hasattr(e, 'name') and e.name == "sense")
        self.assertFalse(sense_ef.is_action)

    def test_volatile_annotations_survive_import(self):
        src = 'import "libant"'
        prog = Parser(tokenize(src)).parse_program()
        _resolved, packages, _pkg_externs = resolve_imports(prog)
        ant_exports = packages["ant"]
        sense_ef = next(e for e in ant_exports if hasattr(e, 'name') and e.name == "sense")
        self.assertTrue(sense_ef.is_volatile)
        self.assertIsNotNone(sense_ef.stable_predicate)
        probe_ef = next(e for e in ant_exports if hasattr(e, 'name') and e.name == "probe")
        self.assertTrue(probe_ef.is_volatile)
        self.assertIsNotNone(probe_ef.stable_predicate)
        smell_ef = next(e for e in ant_exports if hasattr(e, 'name') and e.name == "smell")
        self.assertTrue(smell_ef.is_volatile)
        self.assertIsNone(smell_ef.stable_predicate)
        carrying_ef = next(e for e in ant_exports if hasattr(e, 'name') and e.name == "carrying")
        self.assertFalse(carrying_ef.is_volatile)
        self.assertIsNone(carrying_ef.stable_predicate)

    def test_contains_post_move(self):
        out = compile_src(MINIMAL)
        self.assertIn("__post_move:", out)

    def test_action_then_become(self):
        src = """\
import "libant"
register dir, dx, dy, next_st, last_dir
init { dx = 0 become s }
state s {
    move(RANDOM)
    become s
}
"""
        out = compile_src(src)
        self.assertIn("MOVE", out)
        self.assertIn("JMP s", out)

    def test_import_ant_shorthand(self):
        src = """\
import "ant"
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

    def test_import_ant_qualified(self):
        src = """\
import "ant"
register dir, dx, dy, next_st, last_dir
init { dx = 0 become s }
state s {
    ant.move(ant.RANDOM)
    become s
}
"""
        out = compile_src(src)
        self.assertIn("MOVE", out)


class TestExternRegisterDCE(unittest.TestCase):
    def test_unbound_extern_no_crash(self):
        """Program that imports ant but doesn't bind dx/dy should compile without errors."""
        src = """\
import "libant"
using ant
register dir, next_st
init { become s }
state s {
    move(RANDOM)
    become s
}
"""
        out = compile_src(src)
        self.assertIn("MOVE", out)

    def test_bound_extern_compiles(self):
        """Program that binds extern registers should compile normally."""
        src = """\
import "libant"
using ant
register dir, x(ant.dx), y(ant.dy), heading(ant.last_dir), next_st
init { x = 0 y = 0 become s }
state s {
    move(RANDOM)
    become s
}
"""
        out = compile_src(src)
        self.assertIn("MOVE", out)

    def test_extern_registers_detected_in_packages(self):
        """resolve_imports should detect extern register declarations."""
        from swarm.tokenizer import tokenize
        from swarm.parser import Parser
        src = 'import "libant"'
        prog = Parser(tokenize(src)).parse_program()
        _resolved, _packages, pkg_externs = resolve_imports(prog)
        self.assertIn("ant", pkg_externs)
        self.assertIn("dx", pkg_externs["ant"])
        self.assertIn("dy", pkg_externs["ant"])
        self.assertIn("last_dir", pkg_externs["ant"])


class TestDCEPass(unittest.TestCase):
    def test_dead_code_after_jmp_removed(self):
        from swarm.optimize.dce import dce
        lines = [
            "main:",
            "  SET r1 0",
            "  JMP done",
            "  SET r2 1",
            "  SET r3 2",
            "done:",
            "  SET r4 3",
        ]
        result = dce(lines)
        self.assertIn("  SET r1 0", result)
        self.assertIn("  JMP done", result)
        self.assertNotIn("  SET r2 1", result)
        self.assertNotIn("  SET r3 2", result)
        self.assertIn("done:", result)
        self.assertIn("  SET r4 3", result)

    def test_noop_set_removed(self):
        from swarm.optimize.dce import dce
        lines = [
            "  SET r1 r1",
            "  SET r1 r2",
        ]
        result = dce(lines)
        self.assertNotIn("  SET r1 r1", result)
        self.assertIn("  SET r1 r2", result)

    def test_duplicate_labels_removed(self):
        from swarm.optimize.dce import dce
        lines = [
            "label:",
            "label:",
            "  SET r1 0",
        ]
        result = dce(lines)
        self.assertEqual(result.count("label:"), 1)
        self.assertIn("  SET r1 0", result)

    def test_jump_target_preserved_after_jmp(self):
        from swarm.optimize.dce import dce
        lines = [
            "  JMP a",
            "  SET r1 0",
            "b:",
            "  SET r2 1",
        ]
        result = dce(lines)
        self.assertNotIn("  SET r1 0", result)
        self.assertIn("b:", result)
        self.assertIn("  SET r2 1", result)


if __name__ == "__main__":
    unittest.main()
