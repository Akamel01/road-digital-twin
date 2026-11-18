import re
from pathlib import Path

TS = Path("web/lib/labeltoolbar.ts")


def _entries(text: str, name: str):
    # isolate the array assigned to the named constant
    m = re.search(rf"export const {name}\b[^=]*=\s*\[(.*?)\];", text, re.DOTALL)
    assert m, f"{name} not found"
    body = m.group(1)
    # each entry is { id: "...", label: "..." } (order may vary)
    objs = re.findall(r"\{\s*([^}]*)\}", body, re.DOTALL)
    assert objs, f"no entries in {name}"
    out = []
    for o in objs:
        idm = re.search(r'\bid\s*:\s*"([^"]*)"', o)
        labm = re.search(r'\blabel\s*:\s*"([^"]*)"', o)
        assert idm is not None, f"entry in {name} missing id"
        assert labm is not None, f"entry in {name} missing label"
        out.append((idm.group(1), labm.group(1)))
    return out


def test_mode_buttons():
    text = TS.read_text()
    entries = _entries(text, "MODE_BUTTONS")
    assert len(entries) == 4
    for ident, label in entries:
        assert ident, "empty id"
        assert label.strip(), "empty label"


def test_layer_buttons():
    text = TS.read_text()
    entries = _entries(text, "LAYER_BUTTONS")
    assert len(entries) == 3
    for ident, label in entries:
        assert ident, "empty id"
        assert label.strip(), "empty label"
