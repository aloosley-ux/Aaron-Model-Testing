import pytest

from aaron_model_testing.scoring import score
from aaron_model_testing.suite import load_suite


@pytest.mark.parametrize(
    "answer,passed", [("READY", True), (" READY\n", True), ("Ready", False), ("READY please", False)]
)
def test_exact_instruction(answer, passed):
    assert score(answer, {"type": "exact", "expected": "READY"})["passed"] == passed


@pytest.mark.parametrize(
    "answer",
    ['```json\n{"n": 1}\n```', '{"n":1,"n":2}', '{"n": NaN}', '{"n":"1"}', '{"n":1,"x":2}', 'prefix {"n":1}'],
)
def test_strict_json_rejects_fake_compliance(answer):
    rule = {
        "type": "json",
        "expected": {"n": 1},
        "schema": {
            "type": "object",
            "required": ["n"],
            "additionalProperties": False,
            "properties": {"n": {"type": "integer"}},
        },
    }
    assert not score(answer, rule)["passed"]
    assert score('{"n":1}', rule)["passed"]


def test_native_tool_and_restraint():
    schema = {
        "type": "object",
        "required": ["path"],
        "additionalProperties": False,
        "properties": {"path": {"type": "string"}},
    }
    rule = {"type": "tool", "name": "read_file", "arguments": {"path": "notes.txt"}, "schema": schema}
    call = {"function": {"name": "read_file", "arguments": '{"path":"notes.txt"}'}}
    assert score("", rule, [call])["passed"]
    assert not score("", rule, [call, call])["passed"]
    assert not score("13", {"type": "restraint", "expected": "13"}, [call])["passed"]


def test_coding_cases_and_no_host_execution():
    suite, _ = load_suite()
    rule = next(t["rule"] for t in suite["tests"] if t["id"] == "code-positive")
    correct = "def sum_positive(values):\n    result = 0\n    for v in values:\n        if v > 0:\n            result += v\n    return result"
    assert score(correct, rule)["passed"]
    assert not score("def sum_positive(values):\n    return 10", rule)["passed"]
    for forbidden in [
        "import os\ndef sum_positive(values): return 10",
        'def sum_positive(values):\n    return eval("1+1")',
        "def sum_positive(values):\n    return values.__class__",
        "def sum_positive(values):\n    return [0] * 1000000000",
    ]:
        result = score(forbidden, rule)
        assert not result["passed"]
        assert result["detail"]


def test_bounded_recursion():
    rule = {"type": "code", "function": "f", "cases": [{"args": [1], "expected": 1}]}
    result = score("def f(v):\n    return f(v)", rule)
    assert not result["passed"] and "depth" in result["detail"]


def test_reused_graders_and_rubric():
    assert score("The answer is 42", {"type": "number", "expected": 42})["passed"]
    assert not score("42 then 9", {"type": "number", "expected": 42})["passed"]
    assert score("hello Mira", {"type": "rubric", "contains_all": ["Mira"], "forbidden": ["Lee"]})["passed"]
    assert score("AX-12", {"type": "regex", "pattern": "^AX-[0-9]+$"})["passed"]
