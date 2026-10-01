import copy

import pytest

from aaron_model_testing.evidence import diagnose, enrich_summary, native_metrics, present_record
from aaron_model_testing.grading import grade_result


def sample(answer="OK", rule=None, **values):
    rule = rule or {"type": "exact", "expected": "OK"}
    result = {
        "type": "capability",
        "success": True,
        "response": answer,
        "finish_reason": "stop",
        "category": "reasoning",
        "test": {"rule": rule},
        **values,
    }
    result.update(grade_result(result, rule))
    return result


@pytest.mark.parametrize(
    "answer,rule,values,reason",
    [
        ("wrong", None, {}, "wrong_answer"),
        ("wrong", None, {"category": "extraction"}, "extraction_mismatch"),
        ("OK", None, {"finish_reason": "length"}, "token_budget_truncation"),
        ("<think>unfinished", None, {}, "unavailable_grade"),
        ("partial", None, {"success": False, "error_kind": "timeout"}, "timeout"),
        ("partial", None, {"success": False, "error_kind": "cancelled"}, "cancelled"),
        ("oops", {"type": "json", "schema": {"type": "object"}}, {}, "malformed_structured_output"),
        ("[]", {"type": "json", "schema": {"type": "object"}}, {}, "schema_failure"),
        (
            "",
            {"type": "tool", "name": "lookup", "schema": {"type": "object"}, "arguments": {}},
            {"tool_calls": [{"function": {"name": "lookup", "arguments": "{"}}]},
            "malformed_tool_call",
        ),
        (
            "",
            {"type": "tool", "name": "lookup", "schema": {"type": "object"}, "arguments": {}},
            {"tool_calls": [{"function": {"name": "other", "arguments": "{}"}}]},
            "tool_selection_failure",
        ),
    ],
)
def test_failure_diagnostics_do_not_change_grades_or_raw(answer, rule, values, reason):
    result = sample(answer, rule, **values)
    original = copy.deepcopy(result)
    assert diagnose(result)["failure_reason"] == reason
    assert result == original


def test_native_zero_counts_and_unavailable_splits_are_not_guessed():
    assert native_metrics({"prompt_tokens": 0}, {"prompt_n": 4})["input_tokens"] == 0
    metrics = native_metrics(
        {"completion_tokens": 15, "completion_tokens_details": {"reasoning_tokens": 10}},
        {"prompt_ms": 2, "predicted_ms": 20},
    )
    assert metrics["reasoning_tokens"] == 10 and metrics["final_answer_tokens"] is None
    assert metrics["inference_duration_ms"] == 22
    result = sample("<think>abc</think>OK", metrics={**metrics, "ttfa_ms": 1})
    assert diagnose(result)["ttfa_ms"] is None


def test_unknown_grader_rule_is_harness_failure_and_no_correct_answer_ratio():
    result = sample("x", {"type": "unknown"}, metrics={"output_tokens": 1})
    assert diagnose(result)["failure_reason"] == "parser_or_harness_error"
    summary = enrich_summary({}, [result], {"status": "completed", "timing": {"active_seconds": 1}})
    assert summary["efficiency"]["output_tokens_per_correct_answer"] is None


def test_totals_include_wrong_truncated_and_partial_work_and_null_incomplete_counts():
    records = [
        sample(metrics={"input_tokens": 10, "output_tokens": 2, "latency_ms": 100}),
        sample("bad", metrics={"input_tokens": 10, "output_tokens": 18, "latency_ms": 400}),
        sample(
            "cut",
            finish_reason="length",
            metrics={"input_tokens": 10, "output_tokens": 30, "latency_ms": 500},
        ),
    ]
    record = {"status": "completed", "stage": "capability", "timing": {"active_seconds": 60}}
    result = enrich_summary({}, records, record)
    assert result["tokens"]["output_tokens"]["total"] == 50
    assert result["tokens"]["reasoning_tokens"]["total"] is None
    assert result["capability_response_tokens"]["median"] == 18
    assert result["capability_response_tokens"]["p95"] == 30
    assert result["efficiency"]["correct_capability_samples_per_minute"] == 1
    assert result["efficiency"]["output_tokens_per_correct_answer"] == 50
    assert result["failure_reasons"] == {"wrong_answer": 1, "token_budget_truncation": 1}
    records.append(
        sample(
            "partial", success=False, error_kind="cancelled", metrics={"input_tokens": 10, "latency_ms": 50}
        )
    )
    result = enrich_summary({}, records, {**record, "status": "cancelled"})
    assert result["partial"] and not result["qualification_eligible"]
    assert result["tokens"]["output_tokens"]["total"] == 50
    assert not result["tokens"]["output_tokens"]["complete"]
    assert result["efficiency"]["output_tokens_per_correct_answer"] is None


def test_legacy_timestamp_reads_and_regrade_inference_duration_are_safe():
    record = {
        "status": "completed",
        "stage": "full",
        "created_at": "2026-10-01T00:01:00+00:00",
        "finished_at": "2026-10-01T00:02:10+00:00",
        "summary": {"attempts": 10},
    }
    original = copy.deepcopy(record)
    result = present_record(record)
    assert result["timing"]["active_seconds"] == 70
    assert result["timing"]["queue_wait_seconds"] is None and record == original
    assert present_record({**record, "finished_at": "bad"})["timing"]["active_seconds"] is None
    assert (
        present_record({**record, "finished_at": "2026-10-01T00:00:00+00:00"})["timing"]["active_seconds"]
        is None
    )
    derived = {
        **record,
        "created_at": "2026-10-01T01:00:00+00:00",
        "regrade": {
            "inference_created_at": record["created_at"],
            "inference_finished_at": record["finished_at"],
        },
    }
    assert present_record(derived)["timing"]["active_seconds"] == 70
