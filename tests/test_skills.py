"""Skill canonicalization: aliases collapse, unknowns survive (flagged)."""
import pytest

from transformer.skills import canonicalize_skill, canonicalize_skill_name


@pytest.mark.parametrize("raw,expected", [
    ("js", "JavaScript"), ("JavaScript", "JavaScript"), ("react.js", "React"),
    ("k8s", "Kubernetes"), ("golang", "Go"), ("py", "Python"),
    ("postgres", "PostgreSQL"), ("node", "Node.js"),
])
def test_known_aliases_collapse(raw, expected):
    cs = canonicalize_skill(raw)
    assert cs.name == expected and cs.canonical is True


def test_unknown_skill_kept_but_flagged():
    cs = canonicalize_skill("Quantum Widgetry")
    assert cs.name == "Quantum Widgetry" and cs.canonical is False


def test_garbage_dropped():
    assert canonicalize_skill("") is None
    assert canonicalize_skill(None) is None


def test_name_helper():
    assert canonicalize_skill_name("TS") == "TypeScript"
