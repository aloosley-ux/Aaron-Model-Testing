import json

import pytest

from aaron_model_testing.aggregation import aggregate
from aaron_model_testing.answers import extract_answer
from aaron_model_testing.grading import grade_result
from aaron_model_testing.scoring import score


@pytest.mark.parametrize("answer", ["READY", "apple, river, zebra", "first\nsecond"])
def test_exact_after_reasoning_preserves_raw_and_reasoning(answer):
    raw = " \n<think>reasoning...\ncheck</think> \n" + answer + " \n"
    result = {"response": raw, "success": True, "reasoning": "", "events": [{"raw": raw}]}
    rule = {"type": "exact", "expected": answer}
    graded = {**result, **grade_result(result, rule)}
    assert graded["grade"]["score"] == score(answer, rule)["score"] == 1
    assert graded["final_answer"] == answer
    assert graded["reasoning"] == "reasoning...\ncheck"
    assert graded["response"] == raw and graded["events"] == result["events"]
    assert result["reasoning"] == ""  # Does not mutate input evidence.


def test_json_schema_and_literal_tags_remain_strict():
    answer = json.dumps({"text": "<think>literal</think>", "count": 2})
    rule = {
        "type": "json",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text", "count"],
            "properties": {"text": {"type": "string"}, "count": {"type": "integer"}},
        },
    }
    result = grade_result({"success": True, "response": "<think>plan</think>\n" + answer}, rule)
    assert result["grade"]["passed"]
    assert result["final_answer"] == answer
    assert extract_answer(answer)["final_answer"] == answer
    assert not grade_result(
        {"success": True, "response": "<think>plan</think>```json\n" + answer + "\n```"}, rule
    )["grade"]["passed"]


def test_native_reasoning_preferred_and_tool_arguments_never_stripped():
    call = {"function": {"name": "lookup", "arguments": '{"text":"<think>literal</think>"}'}}
    rule = {
        "type": "tool",
        "name": "lookup",
        "schema": {"type": "object"},
        "arguments": {"text": "<think>literal</think>"},
    }
    result = grade_result(
        {"success": True, "response": "<think>embedded</think>", "reasoning": "native", "tool_calls": [call]},
        rule,
    )
    assert result["grade"]["passed"] and result["reasoning"] == "native"
    assert result["embedded_reasoning"] == "embedded"
    assert result["answer_extraction"]["source"] == "native"
    assert call["function"]["arguments"] == '{"text":"<think>literal</think>"}'
    assert not grade_result({"success": True, "response": "<think>plan</think>lookup(text='x')"}, rule)[
        "grade"
    ]["passed"]
    restraint = {"type": "restraint", "expected": "READY"}
    assert not grade_result(
        {"success": True, "response": "<think>x</think>READY", "tool_calls": [call]}, restraint
    )["grade"]["passed"]


@pytest.mark.parametrize(
    "raw",
    [
        "READY",
        " \nREADY\n",
        "<answer>READY</answer>",
        "code='<think>literal</think>'",
        "<thinker>READY</thinker>",
    ],
)
def test_no_reasoning_and_arbitrary_markup_are_not_removed(raw):
    fields = extract_answer(raw)
    assert fields["final_answer"] == raw.strip()
    assert fields["reasoning"] == ""
    assert fields["answer_extraction"]["status"] == "valid"


@pytest.mark.parametrize(
    "raw",
    [
        "<think>READY",
        "</think>READY",
        "<think",
        "<think />READY",
        "<think >x</think>READY",
        "<think><think>x</think>READY",
        "<think>x</think></think>READY",
    ],
)
def test_malformed_reasoning_is_unavailable_without_guessing(raw):
    result = grade_result({"success": True, "response": raw}, {"type": "exact", "expected": "READY"})
    assert result["final_answer"] is None and result["grade"]["score"] is None
    assert result["grade"]["valid"] is False
    summary = aggregate([{"type": "capability", "category": "instructions", "success": True, **result}])
    assert summary["capability"] is None and summary["capability_status"] == "invalid"
    assert summary["reliability"] == 1


def test_multiple_blocks_and_truncated_or_failed_streams():
    assert extract_answer("<think>one</think>\n<think>two</think>READY")["final_answer"] == "READY"
    for values in ({"success": True, "finish_reason": "length"}, {"success": False, "error": "OOM"}):
        result = grade_result({"response": "<think>READY", **values}, {"type": "exact", "expected": "READY"})
        assert result["grade"]["score"] == 0 and result["grade"]["valid"]
