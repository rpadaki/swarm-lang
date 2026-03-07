"""Tests for swarm.compiler."""

import unittest
from pathlib import Path

from swarm.tokenizer import tokenize
from swarm.parser import Parser
from swarm.compiler import Compiler, resolve_imports, _find_module

# source_dir for tests: resolve imports relative to the repo's lib/ parent
LIB_PARENT = Path(__file__).resolve().parent.parent / "lib"


def compile_src(src: str) -> str:
    prog = Parser(tokenize(src)).parse_program()
    prog, packages, pkg_externs = resolve_imports(prog, source_dir=LIB_PARENT)
    return Compiler(packages, pkg_externs).compile(prog)


MINIMAL = """\
import "ant"
using ant
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
    def test_find_module_ant_dir(self):
        p = _find_module("ant", LIB_PARENT)
        self.assertIsNotNone(p)
        self.assertTrue(p.is_dir())

    def test_resolve_imports_brings_in_exports(self):
        src = 'import "ant"\nusing ant'
        prog = Parser(tokenize(src)).parse_program()
        resolved, _packages, _pkg_externs = resolve_imports(prog, source_dir=LIB_PARENT)
        names = [n.name for n in resolved if hasattr(n, "name")]
        self.assertIn("sense", names)
        self.assertIn("probe", names)
        self.assertIn("move", names)

    def test_import_ant_creates_package(self):
        src = 'import "ant"'
        prog = Parser(tokenize(src)).parse_program()
        _resolved, packages, _pkg_externs = resolve_imports(prog, source_dir=LIB_PARENT)
        self.assertIn("ant", packages)

    def test_missing_module_raises(self):
        src = 'import "nonexistent_module"'
        prog = Parser(tokenize(src)).parse_program()
        with self.assertRaises(SyntaxError):
            resolve_imports(prog, source_dir=LIB_PARENT)


class TestConsts(unittest.TestCase):
    def test_const_substitution(self):
        src = """\
import "ant"
using ant
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
import "ant"
using ant
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
import "ant"
using ant
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
        src = 'import "ant"'
        prog = Parser(tokenize(src)).parse_program()
        _resolved, packages, _pkg_externs = resolve_imports(prog, source_dir=LIB_PARENT)
        self.assertIn("ant", packages)

    def test_package_exports_available_qualified(self):
        src = """\
import "ant"
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

    def test_action_func_is_action_flag(self):
        src = 'import "ant"'
        prog = Parser(tokenize(src)).parse_program()
        _resolved, packages, _pkg_externs = resolve_imports(prog, source_dir=LIB_PARENT)
        ant_exports = packages["ant"]
        move_ef = next(e for e in ant_exports if hasattr(e, 'name') and e.name == "move")
        self.assertTrue(move_ef.is_action)
        sense_ef = next(e for e in ant_exports if hasattr(e, 'name') and e.name == "sense")
        self.assertFalse(sense_ef.is_action)

    def test_volatile_annotations_survive_import(self):
        src = 'import "ant"'
        prog = Parser(tokenize(src)).parse_program()
        _resolved, packages, _pkg_externs = resolve_imports(prog, source_dir=LIB_PARENT)
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

    def test_no_post_move(self):
        out = compile_src(MINIMAL)
        self.assertNotIn("__post_move:", out)

    def test_action_then_become(self):
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
        self.assertIn("JMP s", out)


class TestExternRegisterDCE(unittest.TestCase):
    def test_unbound_extern_no_crash(self):
        src = """\
import "ant"
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
        src = """\
import "ant"
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
        src = 'import "ant"'
        prog = Parser(tokenize(src)).parse_program()
        _resolved, _packages, pkg_externs = resolve_imports(prog, source_dir=LIB_PARENT)
        self.assertIn("ant", pkg_externs)
        self.assertIn("dx", pkg_externs["ant"])
        self.assertIn("dy", pkg_externs["ant"])
        self.assertIn("last_dir", pkg_externs["ant"])


class TestRegisterInitializers(unittest.TestCase):
    def test_simple_initializer(self):
        src = """\
import "ant"
using ant
register (
    dir
    x = 0
    y = 0
    next_st
    last_dir
)
init { become s }
state s { move(RANDOM) become s }
"""
        out = compile_src(src)
        self.assertIn("main:", out)
        lines = out.split("\n")
        main_idx = next(i for i, l in enumerate(lines) if l.strip() == "main:")
        init_lines = []
        for l in lines[main_idx+1:]:
            if l.strip().startswith("JMP "):
                break
            init_lines.append(l.strip())
        self.assertIn("SET r2 0", init_lines)
        self.assertIn("SET r3 0", init_lines)

    def test_expr_initializer(self):
        src = """\
import "ant"
using ant
register (
    dir
    heading = id() % 4 + 1
    next_st
    last_dir
)
init { become s }
state s { move(RANDOM) become s }
"""
        out = compile_src(src)
        self.assertIn("ID r2", out)
        self.assertIn("MOD r2 4", out)
        self.assertIn("ADD r2 1", out)

    def test_const_initializer(self):
        src = """\
import "ant"
using ant
const GREEN_START = 255
register (
    dir
    mark_str = GREEN_START
    next_st
    last_dir
)
init { become s }
state s { move(RANDOM) become s }
"""
        out = compile_src(src)
        self.assertIn("SET r2 255", out)

    def test_initializers_before_init_body(self):
        src = """\
import "ant"
using ant
register (
    dir
    x = 42
    next_st
    last_dir
)
init { become s }
state s { move(RANDOM) become s }
"""
        out = compile_src(src)
        lines = out.split("\n")
        main_idx = next(i for i, l in enumerate(lines) if l.strip() == "main:")
        set_idx = next(i for i, l in enumerate(lines) if "SET r2 42" in l)
        jmp_idx = next(i for i, l in enumerate(lines) if "JMP s" in l)
        self.assertGreater(set_idx, main_idx)
        self.assertLess(set_idx, jmp_idx)

    def test_initializers_without_init_block(self):
        src = """\
import "ant"
using ant
register (
    dir
    x = 0
    next_st
    last_dir
)
state s { move(RANDOM) become s }
"""
        out = compile_src(src)
        self.assertIn("main:", out)
        self.assertIn("SET r2 0", out)

    def test_full_design_example(self):
        src = """\
import "ant"
using ant
const GREEN_START = 255
register (
    dir
    x(ant.dx) = 0
    y(ant.dy) = 0
    heading(ant.last_dir) = id() % 4 + 1
    mark_str = GREEN_START
    next_st
    tmp
)
init { become search }
state search {
    move(RANDOM)
    become search
}
"""
        out = compile_src(src)
        self.assertIn("main:", out)
        self.assertIn("SET r2 0", out)
        self.assertIn("SET r3 0", out)
        self.assertIn("ID r4", out)
        self.assertIn("MOD r4 4", out)
        self.assertIn("ADD r4 1", out)
        self.assertIn("SET r5 255", out)


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
        self.assertNotIn("  SET r2 1", result)
        self.assertNotIn("  SET r3 2", result)
        self.assertIn("done:", result)
        self.assertIn("  SET r4 3", result)
        # JMP done -> done: is a fallthrough, so JMP is eliminated
        self.assertNotIn("  JMP done", result)

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
            "a:",
            "  SET r2 1",
            "b:",
            "  SET r3 2",
        ]
        result = dce(lines)
        self.assertNotIn("  SET r1 0", result)
        self.assertIn("a:", result)
        self.assertIn("  SET r2 1", result)
        # b: is a user label (no __ prefix), preserved even if unreferenced
        self.assertIn("b:", result)

    def test_dead_unreferenced_label_removed(self):
        from swarm.optimize.dce import dce
        lines = [
            "  JMP a",
            "__dead_label:",
            "  SET r1 0",
            "a:",
            "  SET r2 1",
        ]
        result = dce(lines)
        self.assertNotIn("__dead_label:", result)
        self.assertNotIn("  SET r1 0", result)
        self.assertIn("a:", result)

    def test_jmp_to_next_label_removed(self):
        from swarm.optimize.dce import dce
        lines = [
            "  SET r1 0",
            "  JMP __L_1",
            "__L_1:",
            "  SET r2 1",
        ]
        result = dce(lines)
        self.assertNotIn("  JMP __L_1", result)
        self.assertIn("  SET r2 1", result)

    def test_jmp_to_next_label_kept_when_different(self):
        from swarm.optimize.dce import dce
        lines = [
            "  JMP other",
            "__L_1:",
            "  SET r2 1",
        ]
        result = dce(lines)
        self.assertIn("  JMP other", result)

    def test_unreferenced_internal_label_removed(self):
        from swarm.optimize.dce import dce
        lines = [
            "  JMP a",
            "a:",
            "  SET r1 0",
            "__orphan:",
            "  SET r2 1",
        ]
        result = dce(lines)
        self.assertNotIn("__orphan:", result)
        self.assertIn("a:", result)

    def test_user_labels_preserved(self):
        from swarm.optimize.dce import dce
        lines = [
            "main:",
            "  JMP search",
            "search:",
            "  SET r1 0",
        ]
        result = dce(lines)
        self.assertIn("main:", result)
        self.assertIn("search:", result)


if __name__ == "__main__":
    unittest.main()
