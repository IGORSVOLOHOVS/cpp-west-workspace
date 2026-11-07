"""Judge tests/manual/tests.json where every other file is judged (section 9)."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIST = ROOT / "tests" / "manual" / "tests.json"
LEGAL_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,60}")
CONTROL = re.compile(r"[\x00-\x1f]")


def strings_in(value: object) -> list[str]:
    """Every string a JSON value holds, however deep."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in strings_in(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in strings_in(item)]
    return []


def read_list() -> dict:
    raw = LIST.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "tests.json starts with a BOM"
    return json.loads(raw.decode("utf-8"))


def test_the_list_has_a_known_shape() -> None:
    document = read_list()
    assert document["version"] == 1
    assert isinstance(document["tests"], list)


def test_every_entry_is_complete() -> None:
    seen: set[str] = set()
    for entry in read_list()["tests"]:
        identifier = entry["id"]
        assert LEGAL_ID.fullmatch(identifier) and identifier != "verdict", identifier
        assert identifier not in seen, f"{identifier} appears twice"
        seen.add(identifier)
        assert isinstance(entry["title"], str)
        assert isinstance(entry["expected"], str)
        assert isinstance(entry["steps"], list) and all(isinstance(step, str) for step in entry["steps"])
        assert isinstance(entry.get("issue", 0), int)
        assert isinstance(entry.get("blocking", True), bool)
        assert isinstance(entry.get("needs", ""), str)
        assert not any(CONTROL.search(text) for text in strings_in(entry)), identifier
