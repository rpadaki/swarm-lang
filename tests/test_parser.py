"""Tests for swarm.parser."""

import unittest

from swarm.tokenizer import tokenize
from swarm.parser import Parser
from swarm.ast import (
    ActionStmt, Assignment, BinExpr, Become, BehaviorDef, CallExpr, Const,
    ExportConst, ExportFunc, FuncCall, FuncDef, IfStmt, Import, InitBlock,
    LoopStmt, MatchCase, MatchStmt, PackageDecl, RegDecl, StateBlock,
    StateFromBehavior, UsingDecl, WhileStmt, BoolDecl, TagDecl,
)


def parse(src: str):
    return Parser(tokenize(src)).parse_program()


class TestMinimalProgram(unittest.TestCase):
    def test_const_and_state(self):
        prog = parse("const X = 10\nstate foo { become foo }")
        self.assertIsInstance(prog[0], Const)
        self.assertEqual(prog[0].name, "X")
        self.assertEqual(prog[0].value, "10")
        self.assertIsInstance(prog[1], StateBlock)
        self.assertEqual(prog[1].name, "foo")
        self.assertEqual(len(prog[1].body), 1)
        self.assertIsInstance(prog[1].body[0], Become)
        self.assertEqual(prog[1].body[0].target, "foo")


class TestRegisterDeclaration(unittest.TestCase):
    def test_single_register(self):
        prog = parse("register x")
        self.assertIsInstance(prog[0], RegDecl)
        self.assertEqual(prog[0].names, ["x"])

    def test_multiple_registers(self):
        prog = parse("register a, b, c")
        self.assertEqual(prog[0].names, ["a", "b", "c"])


class TestControlFlow(unittest.TestCase):
    def test_if_else(self):
        prog = parse("state s { if x == 1 { become a } else { become b } }")
        body = prog[0].body
        self.assertEqual(len(body), 1)
        stmt = body[0]
        self.assertIsInstance(stmt, IfStmt)
        self.assertEqual(stmt.cond, ("x", "==", "1"))
        self.assertIsNotNone(stmt.else_body)

    def test_if_without_else(self):
        prog = parse("state s { if x != 0 { become a } }")
        stmt = prog[0].body[0]
        self.assertIsInstance(stmt, IfStmt)
        self.assertIsNone(stmt.else_body)

    def test_while(self):
        prog = parse("state s { while x < 4 { x = x + 1 } }")
        stmt = prog[0].body[0]
        self.assertIsInstance(stmt, WhileStmt)
        self.assertEqual(stmt.cond, ("x", "<", "4"))

    def test_loop(self):
        prog = parse("state s { loop { break } }")
        stmt = prog[0].body[0]
        self.assertIsInstance(stmt, LoopStmt)
        self.assertEqual(len(stmt.body), 1)

    def test_match(self):
        prog = parse("state s { match x { case 1 { become a } case 2 { become b } default { become c } } }")
        stmt = prog[0].body[0]
        self.assertIsInstance(stmt, MatchStmt)
        self.assertEqual(stmt.var, "x")
        self.assertEqual(len(stmt.cases), 2)
        self.assertIsInstance(stmt.cases[0], MatchCase)
        self.assertEqual(stmt.cases[0].value, "1")
        self.assertIsNotNone(stmt.default_body)


class TestAssignment(unittest.TestCase):
    def test_simple_assignment(self):
        prog = parse("state s { x = 5 }")
        stmt = prog[0].body[0]
        self.assertIsInstance(stmt, Assignment)
        self.assertEqual(stmt.target, "x")
        self.assertEqual(stmt.expr, "5")

    def test_compound_assignment(self):
        for op in ["+", "-", "*", "/", "%", "&", "|", "^"]:
            prog = parse(f"state s {{ x {op}= 1 }}")
            stmt = prog[0].body[0]
            self.assertIsInstance(stmt, Assignment)
            self.assertEqual(stmt.target, "x")
            self.assertIsInstance(stmt.expr, BinExpr)
            self.assertEqual(stmt.expr.left, "x")
            self.assertEqual(stmt.expr.op, op)
            self.assertEqual(stmt.expr.right, "1")


class TestOperatorPrecedence(unittest.TestCase):
    def test_mul_before_add(self):
        prog = parse("state s { x = a + b * c }")
        expr = prog[0].body[0].expr
        self.assertIsInstance(expr, BinExpr)
        self.assertEqual(expr.op, "+")
        self.assertEqual(expr.left, "a")
        self.assertIsInstance(expr.right, BinExpr)
        self.assertEqual(expr.right.op, "*")

    def test_add_before_bitwise(self):
        prog = parse("state s { x = a & b + c }")
        expr = prog[0].body[0].expr
        self.assertIsInstance(expr, BinExpr)
        self.assertEqual(expr.op, "&")
        self.assertEqual(expr.left, "a")
        self.assertIsInstance(expr.right, BinExpr)
        self.assertEqual(expr.right.op, "+")

    def test_parenthesized_override(self):
        prog = parse("state s { x = (a + b) * c }")
        expr = prog[0].body[0].expr
        self.assertIsInstance(expr, BinExpr)
        self.assertEqual(expr.op, "*")
        self.assertIsInstance(expr.left, BinExpr)
        self.assertEqual(expr.left.op, "+")

    def test_shift_between_add_and_bitwise(self):
        prog = parse("state s { x = a + b << c }")
        expr = prog[0].body[0].expr
        # << has prec 4, + has prec 5, so + binds tighter
        self.assertIsInstance(expr, BinExpr)
        self.assertEqual(expr.op, "<<")
        self.assertIsInstance(expr.left, BinExpr)
        self.assertEqual(expr.left.op, "+")


class TestBehavior(unittest.TestCase):
    def test_behavior_with_exits(self):
        prog = parse("""
            behavior wander {
                exit found
                exit lost
                become found
            }
        """)
        beh = prog[0]
        self.assertIsInstance(beh, BehaviorDef)
        self.assertEqual(beh.name, "wander")
        self.assertEqual(beh.exits, ["found", "lost"])
        self.assertEqual(len(beh.body), 1)
        self.assertIsInstance(beh.body[0], Become)

    def test_behavior_with_params(self):
        prog = parse("""
            behavior go(s, d) {
                exit done
                become done
            }
        """)
        beh = prog[0]
        self.assertEqual(beh.params, ["s", "d"])


class TestStateFromBehavior(unittest.TestCase):
    def test_wiring(self):
        prog = parse("""
            behavior w { exit a }
            state s = w { a -> target }
        """)
        sfb = prog[1]
        self.assertIsInstance(sfb, StateFromBehavior)
        self.assertEqual(sfb.name, "s")
        self.assertEqual(sfb.behavior, "w")
        self.assertEqual(sfb.wiring, {"a": "target"})

    def test_wiring_with_args(self):
        prog = parse("""
            behavior b(x) { exit done }
            state s = b(myvar) { done -> next }
        """)
        sfb = prog[1]
        self.assertEqual(sfb.args, ["myvar"])
        self.assertEqual(sfb.wiring, {"done": "next"})


class TestFuncDef(unittest.TestCase):
    def test_simple_func(self):
        prog = parse("func turn_right() { x = 1 }")
        self.assertIsInstance(prog[0], FuncDef)
        self.assertEqual(prog[0].name, "turn_right")
        self.assertEqual(len(prog[0].body), 1)

    def test_export_func_with_params_and_return(self):
        prog = parse("export func sense(target) -> result { x = 1 }")
        ef = prog[0]
        self.assertIsInstance(ef, ExportFunc)
        self.assertEqual(ef.name, "sense")
        self.assertEqual(ef.params, ["target"])
        self.assertEqual(ef.ret, "result")
        self.assertTrue(ef.exported)


class TestImport(unittest.TestCase):
    def test_import(self):
        prog = parse('import "libant"')
        self.assertEqual(len(prog), 1)
        self.assertIsInstance(prog[0], Import)
        self.assertEqual(prog[0].path, "libant")


class TestBoolDecl(unittest.TestCase):
    def test_single_bool(self):
        prog = parse("bool flag")
        self.assertIsInstance(prog[0], BoolDecl)
        self.assertEqual(prog[0].names, ["flag"])

    def test_multiple_bools(self):
        prog = parse("bool a, b, c")
        self.assertEqual(prog[0].names, ["a", "b", "c"])


class TestTagDecl(unittest.TestCase):
    def test_tag_without_index(self):
        prog = parse("tag my_tag")
        self.assertIsInstance(prog[0], TagDecl)
        self.assertEqual(prog[0].name, "my_tag")
        self.assertIsNone(prog[0].index)

    def test_tag_with_index(self):
        prog = parse("tag 3 my_tag")
        self.assertEqual(prog[0].name, "my_tag")
        self.assertEqual(prog[0].index, 3)


class TestInitBlock(unittest.TestCase):
    def test_init(self):
        prog = parse("init { become start }")
        self.assertIsInstance(prog[0], InitBlock)
        self.assertEqual(len(prog[0].body), 1)


class TestPackageDecl(unittest.TestCase):
    def test_package_declaration(self):
        prog = parse("package ant")
        self.assertEqual(len(prog), 1)
        self.assertIsInstance(prog[0], PackageDecl)
        self.assertEqual(prog[0].name, "ant")

    def test_package_with_other_decls(self):
        prog = parse('package ant\nexport const N = 1\nexport func sense(t) -> r { x = 1 }')
        self.assertIsInstance(prog[0], PackageDecl)
        self.assertIsInstance(prog[1], ExportConst)
        self.assertIsInstance(prog[2], ExportFunc)


class TestUsingDecl(unittest.TestCase):
    def test_using_declaration(self):
        prog = parse("using ant")
        self.assertEqual(len(prog), 1)
        self.assertIsInstance(prog[0], UsingDecl)
        self.assertEqual(prog[0].name, "ant")

    def test_using_in_program(self):
        prog = parse('import "libant"\nusing ant\nstate s { become s }')
        self.assertIsInstance(prog[0], Import)
        self.assertIsInstance(prog[1], UsingDecl)
        self.assertIsInstance(prog[2], StateBlock)


class TestExportActionFunc(unittest.TestCase):
    def test_export_action_func(self):
        prog = parse("export action func move(direction) { x = 1 }")
        ef = prog[0]
        self.assertIsInstance(ef, ExportFunc)
        self.assertEqual(ef.name, "move")
        self.assertEqual(ef.params, ["direction"])
        self.assertTrue(ef.exported)
        self.assertTrue(ef.is_action)

    def test_export_action_func_no_params(self):
        prog = parse("export action func pickup() { x = 1 }")
        ef = prog[0]
        self.assertIsInstance(ef, ExportFunc)
        self.assertEqual(ef.name, "pickup")
        self.assertEqual(ef.params, [])
        self.assertTrue(ef.is_action)

    def test_export_non_action_func(self):
        prog = parse("export func sense(target) -> result { x = 1 }")
        ef = prog[0]
        self.assertIsInstance(ef, ExportFunc)
        self.assertFalse(ef.is_action)


class TestQualifiedNames(unittest.TestCase):
    def test_qualified_call_in_expr(self):
        prog = parse("state s { x = ant.sense(FOOD) }")
        stmt = prog[0].body[0]
        self.assertIsInstance(stmt, Assignment)
        self.assertIsInstance(stmt.expr, CallExpr)
        self.assertEqual(stmt.expr.func, "ant.sense")
        self.assertEqual(stmt.expr.args, ["FOOD"])

    def test_qualified_const_in_expr(self):
        prog = parse("state s { x = ant.N }")
        stmt = prog[0].body[0]
        self.assertIsInstance(stmt, Assignment)
        self.assertEqual(stmt.expr, "ant.N")

    def test_qualified_call_in_condition(self):
        prog = parse("state s { if ant.probe(HERE) == FOOD { become s } }")
        stmt = prog[0].body[0]
        self.assertIsInstance(stmt, IfStmt)
        left = stmt.cond[0]
        self.assertIsInstance(left, CallExpr)
        self.assertEqual(left.func, "ant.probe")

    def test_qualified_const_as_arg(self):
        prog = parse("state s { x = sense(ant.FOOD) }")
        stmt = prog[0].body[0]
        self.assertIsInstance(stmt, Assignment)
        self.assertIsInstance(stmt.expr, CallExpr)
        self.assertEqual(stmt.expr.args, ["ant.FOOD"])

    def test_qualified_func_call_stmt(self):
        prog = parse("state s { ant.mark(CH_RED, 100) }")
        stmt = prog[0].body[0]
        self.assertIsInstance(stmt, ActionStmt)
        self.assertEqual(stmt.func, "ant.mark")


class TestActionStmtTransition(unittest.TestCase):
    def test_action_with_arrow(self):
        prog = parse("export func move(d) { x = 1 }\nstate s { move(N) -> s }")
        stmt = prog[1].body[0]
        self.assertIsInstance(stmt, ActionStmt)
        self.assertEqual(stmt.func, "move")
        self.assertEqual(stmt.transition, "s")

    def test_action_without_arrow(self):
        prog = parse("export func move(d) { x = 1 }\nstate s { move(N) become s }")
        stmt = prog[1].body[0]
        self.assertIsInstance(stmt, ActionStmt)
        self.assertEqual(stmt.func, "move")
        self.assertIsNone(stmt.transition)


if __name__ == "__main__":
    unittest.main()
