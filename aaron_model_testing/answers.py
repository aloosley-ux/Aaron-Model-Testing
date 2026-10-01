"""Deterministic, prefix-only reasoning extraction; never sanitise arbitrary markup."""

from __future__ import annotations

import re

PARSER_VERSION = "think-prefix-v1"
_MALFORMED_PREFIX = re.compile(r"</?think(?:\s|>|/|$)")


def extract_answer(response: str, native_reasoning: str = "") -> dict:
    remaining = response.lstrip()
    thoughts = []
    error = None
    while remaining.startswith("<think>"):
        end = remaining.find("</think>", len("<think>"))
        if end < 0:
            thoughts.append(remaining[len("<think>") :])
            error = "Unclosed <think> block; final answer cannot be identified safely"
            break
        thought = remaining[len("<think>") : end]
        if "<think>" in thought or _MALFORMED_PREFIX.match(thought.lstrip()):
            error = "Nested or malformed <think> block"
            thoughts.append(thought)
            break
        thoughts.append(thought)
        remaining = remaining[end + len("</think>") :].lstrip()
    if not error and _MALFORMED_PREFIX.match(remaining):
        error = "Unexpected or malformed reasoning tag at answer boundary"
    embedded = "".join(thoughts)
    return {
        "final_answer": None if error else remaining.strip(),
        "reasoning": native_reasoning or embedded,
        "native_reasoning": native_reasoning,
        "embedded_reasoning": embedded,
        "answer_extraction": {
            "version": PARSER_VERSION,
            "source": "native" if native_reasoning else "embedded" if thoughts else "content",
            "status": "invalid" if error else "valid",
            "error": error,
        },
    }
