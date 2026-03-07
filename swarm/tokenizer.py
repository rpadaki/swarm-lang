"""Tokenizer for the Swarm language."""

import re
from dataclasses import dataclass

TOK_PAT = [
    ("COMMENT",  r"//[^\n]*"),
    ("MCOMMENT", r"/\*[\s\S]*?\*/"),
    ("STRING",   r'"[^"]*"'),
    ("ARROW",    r"->"),
    ("NUMBER",   r"-?\d+"),
    ("IDENT",    r"[A-Za-z_][A-Za-z0-9_]*"),
    ("LBRACE",   r"\{"),
    ("RBRACE",   r"\}"),
    ("LPAREN",   r"\("),
    ("RPAREN",   r"\)"),
    ("COMMA",    r","),
    ("DOT",      r"\."),
    ("OP",       r"[+\-*/%&|^]=|[=!<>]=|:=|<<|>>|[+\-*/%&|^<>=]"),
    ("SKIP",     r"[ \t\r]+"),
    ("NL",       r"\n"),
]
TOK_RE = re.compile("|".join(f"(?P<{n}>{p})" for n, p in TOK_PAT))


@dataclass
class Tok:
    type: str; value: str; line: int


def tokenize(src: str) -> list[Tok]:
    toks, ln = [], 1
    for m in TOK_RE.finditer(src):
        k, v = m.lastgroup, m.group()
        if k == "NL": ln += 1; continue
        if k in ("SKIP", "COMMENT", "MCOMMENT"): ln += v.count("\n"); continue
        toks.append(Tok(k, v, ln))
    return toks
