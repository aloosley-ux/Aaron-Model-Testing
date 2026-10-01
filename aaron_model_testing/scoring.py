"""Strict practical scoring, composing MIT graders/rubrics with schema and tool checks."""

from __future__ import annotations

import json
import re

from jsonschema import Draft202012Validator

from .codecheck import check_code
from .vendor.graders import Grade, exact_number, regex_match
from .vendor.task_quality import TaskRubric, evaluate_text


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Nonstandard JSON constant: {value}")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def score(response: str, rule: dict, tool_calls=None) -> dict:
    try:
        kind = rule["type"]
        grade = Grade(0, False, "")
        if kind == "exact":
            passed = response.strip() == rule["expected"]
            grade = Grade(
                float(passed), passed, "Exact match" if passed else f"Expected {rule['expected']!r}"
            )
        elif kind == "number":
            grade = exact_number(rule["expected"])(response)
        elif kind == "regex":
            grade = regex_match(rule["pattern"], flags=0)(response)
        elif kind == "rubric":
            passed = evaluate_text(response, TaskRubric(**{k: v for k, v in rule.items() if k != "type"}))
            grade = Grade(
                float(passed), passed, "Required/forbidden content checks" if passed else "Rubric mismatch"
            )
        elif kind == "json":
            value = strict_json(response.strip())
            errors = list(Draft202012Validator(rule["schema"]).iter_errors(value))
            matches = "expected" not in rule or value == rule["expected"]
            passed = not errors and matches
            detail = "; ".join(e.message for e in errors) or (
                "Valid schema and value" if matches else "Incorrect JSON value"
            )
            grade = Grade(float(passed), passed, detail)
        elif kind == "tool":
            calls = tool_calls or []
            if len(calls) != 1:
                raise ValueError(f"Expected exactly one native tool call; received {len(calls)}")
            call = calls[0]["function"]
            args = strict_json(call["arguments"])
            errors = list(Draft202012Validator(rule["schema"]).iter_errors(args))
            passed = call["name"] == rule["name"] and not errors and args == rule["arguments"]
            grade = Grade(
                float(passed), passed, "Valid native tool call" if passed else "Tool or arguments mismatch"
            )
        elif kind == "restraint":
            passed = not tool_calls and response.strip() == rule["expected"]
            grade = Grade(
                float(passed),
                passed,
                "Tool restraint" if passed else "Unneeded tool call or incorrect answer",
            )
        elif kind == "code":
            fenced = re.fullmatch(r"\s*```(?:python)?\s*\n(.*?)\n```\s*", response, re.DOTALL)
            code = fenced[1] if fenced else response.strip()
            outcomes = check_code(code, rule)
            passed = all(c["passed"] for c in outcomes)
            return {
                "score": sum(c["passed"] for c in outcomes) / len(outcomes),
                "passed": passed,
                "detail": "All unit cases passed" if passed else "Unit case mismatch",
                "cases": outcomes,
            }
        else:
            raise ValueError(f"Unknown scoring rule {kind}")
        return {"score": grade.score, "passed": grade.passed, "detail": grade.detail}
    except (
        ValueError,
        TypeError,
        KeyError,
        SyntaxError,
        ZeroDivisionError,
        IndexError,
        OverflowError,
    ) as exc:
        return {"score": 0.0, "passed": False, "detail": str(exc)}
