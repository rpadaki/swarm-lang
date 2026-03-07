"""Integration tests: compile every .sw file in examples/ and tests/fixtures/.

Smoke-tests the full pipeline (tokenize -> parse -> resolve_imports -> compile)
for each .sw file. Files that declare too many registers for the current
compiler are marked as expected failures.
"""

import unittest
from pathlib import Path

from swarm.tokenizer import tokenize
from swarm.parser import Parser
from swarm.compiler import Compiler, resolve_imports

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = PROJECT_ROOT / "examples"
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"

# Files that declare 8 user registers overflow the r1-r7 limit.
KNOWN_REGISTER_OVERFLOW = {
    "minimal", "pheromone_trail", "match_demo", "wall_hugger",
    "behavior_demo", "behavior_test", "param_test", "bool_test",
}


def compile_file(path: Path) -> str:
    src = path.read_text()
    prog = Parser(tokenize(src)).parse_program()
    prog, packages = resolve_imports(prog, source_dir=path.parent)
    return Compiler(packages).compile(prog)


def _make_test(path: Path):
    def test(self):
        out = compile_file(path)
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)
    if path.stem in KNOWN_REGISTER_OVERFLOW:
        test = unittest.expectedFailure(test)
    return test


class TestExamples(unittest.TestCase):
    pass


class TestFixtures(unittest.TestCase):
    pass


for sw in sorted(EXAMPLES_DIR.glob("*.sw")):
    setattr(TestExamples, f"test_{sw.stem}", _make_test(sw))

for sw in sorted(FIXTURES_DIR.glob("*.sw")):
    setattr(TestFixtures, f"test_{sw.stem}", _make_test(sw))


if __name__ == "__main__":
    unittest.main()
