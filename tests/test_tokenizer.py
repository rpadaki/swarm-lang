"""Tests for swarm.tokenizer."""

import unittest

from swarm.tokenizer import Tok, tokenize


class TestBasicTokens(unittest.TestCase):
    def test_ident(self):
        toks = tokenize("foo bar_baz _x")
        self.assertEqual([(t.type, t.value) for t in toks], [
            ("IDENT", "foo"), ("IDENT", "bar_baz"), ("IDENT", "_x"),
        ])

    def test_number(self):
        toks = tokenize("42 -1 0")
        nums = [(t.type, t.value) for t in toks]
        self.assertEqual(nums[0], ("NUMBER", "42"))
        self.assertEqual(nums[1], ("NUMBER", "-1"))
        self.assertEqual(nums[2], ("NUMBER", "0"))

    def test_string(self):
        toks = tokenize('"hello" "world"')
        self.assertEqual(len(toks), 2)
        self.assertTrue(all(t.type == "STRING" for t in toks))
        self.assertEqual(toks[0].value, '"hello"')

    def test_braces_parens_comma(self):
        toks = tokenize("{ } ( ) ,")
        types = [t.type for t in toks]
        self.assertEqual(types, ["LBRACE", "RBRACE", "LPAREN", "RPAREN", "COMMA"])

    def test_arrow(self):
        toks = tokenize("->")
        self.assertEqual(len(toks), 1)
        self.assertEqual(toks[0].type, "ARROW")
        self.assertEqual(toks[0].value, "->")


class TestOperators(unittest.TestCase):
    def test_compound_assignment(self):
        ops = ["+=", "-=", "*=", "/=", "%=", "&=", "|=", "^="]
        for op in ops:
            toks = tokenize(f"x {op} 1")
            op_tok = [t for t in toks if t.type == "OP"][0]
            self.assertEqual(op_tok.value, op, f"Failed for {op}")

    def test_comparison_operators(self):
        for op in ["==", "!=", ">=", "<="]:
            toks = tokenize(f"a {op} b")
            op_tok = [t for t in toks if t.type == "OP"][0]
            self.assertEqual(op_tok.value, op)

    def test_shift_operators(self):
        for op in ["<<", ">>"]:
            toks = tokenize(f"x {op} 2")
            op_tok = [t for t in toks if t.type == "OP"][0]
            self.assertEqual(op_tok.value, op)

    def test_walrus_operator(self):
        toks = tokenize("x := expr")
        op_tok = [t for t in toks if t.type == "OP"][0]
        self.assertEqual(op_tok.value, ":=")

    def test_single_char_ops(self):
        for op in ["+", "-", "*", "/", "%", "&", "|", "^", "<", ">", "="]:
            toks = tokenize(f"a {op} b")
            op_tok = [t for t in toks if t.type == "OP"][0]
            self.assertEqual(op_tok.value, op, f"Failed for single op '{op}'")


class TestSkipping(unittest.TestCase):
    def test_line_comment_skipped(self):
        toks = tokenize("foo // this is a comment\nbar")
        self.assertEqual([t.value for t in toks], ["foo", "bar"])

    def test_block_comment_skipped(self):
        toks = tokenize("foo /* multi\nline */ bar")
        self.assertEqual([t.value for t in toks], ["foo", "bar"])

    def test_whitespace_skipped(self):
        toks = tokenize("  a   b  ")
        self.assertEqual(len(toks), 2)


class TestLineTracking(unittest.TestCase):
    def test_newlines_increment_line(self):
        toks = tokenize("a\nb\nc")
        self.assertEqual(toks[0].line, 1)
        self.assertEqual(toks[1].line, 2)
        self.assertEqual(toks[2].line, 3)

    def test_block_comment_line_tracking(self):
        toks = tokenize("a\n/* line2\nline3 */\nb")
        self.assertEqual(toks[0].line, 1)
        self.assertEqual(toks[1].line, 4)


class TestDotToken(unittest.TestCase):
    def test_dot_tokenized(self):
        toks = tokenize("ant.move")
        self.assertEqual(len(toks), 3)
        self.assertEqual(toks[0].type, "IDENT")
        self.assertEqual(toks[0].value, "ant")
        self.assertEqual(toks[1].type, "DOT")
        self.assertEqual(toks[1].value, ".")
        self.assertEqual(toks[2].type, "IDENT")
        self.assertEqual(toks[2].value, "move")

    def test_qualified_call_tokens(self):
        toks = tokenize("ant.move(N)")
        types = [t.type for t in toks]
        self.assertEqual(types, ["IDENT", "DOT", "IDENT", "LPAREN", "IDENT", "RPAREN"])


class TestTokDataclass(unittest.TestCase):
    def test_fields(self):
        t = Tok("IDENT", "foo", 1)
        self.assertEqual(t.type, "IDENT")
        self.assertEqual(t.value, "foo")
        self.assertEqual(t.line, 1)


if __name__ == "__main__":
    unittest.main()
