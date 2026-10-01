"""v1.1 answer extraction around the unchanged, frozen v1 deterministic rules."""

from __future__ import annotations

from .answers import extract_answer
from .scoring import score

GRADER_VERSION = "agent-core-v1.1"


def grade_result(result: dict, rule: dict) -> dict:
    # response and events always retain exactly what the runtime returned.
    fields = extract_answer(
        result.get("response", ""), result.get("native_reasoning", result.get("reasoning", ""))
    )
    if not result.get("success"):
        grade = {"score": 0, "passed": False, "detail": result.get("error") or "Inference failed"}
    elif result.get("finish_reason") == "length":
        grade = {"score": 0, "passed": False, "detail": "Token budget exhausted (truncated response)"}
    elif fields["answer_extraction"]["status"] == "invalid" and rule["type"] != "tool":
        grade = {
            "score": None,
            "passed": None,
            "valid": False,
            "detail": fields["answer_extraction"]["error"],
        }
    else:
        grade = score(fields["final_answer"] or "", rule, result.get("tool_calls"))
    grade.update(version=GRADER_VERSION)
    grade.setdefault("valid", True)
    return {**fields, "grade": grade}
