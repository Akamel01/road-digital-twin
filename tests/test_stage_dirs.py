"""Guard: Stage folder names ('5_features') come from contracts.stage_dir, not literals."""

import ast
import re
from pathlib import Path

from twin.contracts import STAGE_NAMES

# areabuild/areasteps (locked by #404) still carry literals; fake_run builds run folders directly.
ALLOW = {"contracts.py", "areabuild.py", "areasteps.py", "fake_run.py"}
PATTERN = re.compile(r"\d+_(" + "|".join(STAGE_NAMES) + r")\b")


def test_no_stage_folder_literals_outside_contracts():
    hits = []
    for path in sorted(Path(__file__).parent.parent.joinpath("twin").rglob("*.py")):
        if path.name in ALLOW and path.parent.name == "twin":
            continue
        tree = ast.parse(path.read_text())
        docs = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and n.body
            and isinstance(n.body[0], ast.Expr)
        }
        for node in ast.walk(tree):
            if id(node) in docs:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and PATTERN.search(node.value):
                hits.append(f"{path.name}:{node.lineno} {node.value!r}")
    assert not hits, "use contracts.stage_dir instead of: " + ", ".join(hits)
