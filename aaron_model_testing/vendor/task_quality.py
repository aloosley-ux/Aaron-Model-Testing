# Vendored MIT code. See THIRD_PARTY_NOTICES.md and licenses/.
"""Task-quality rubric evaluation for benchmark outputs.

Provides deterministic, objective checks against per-prompt rubrics defined
in a YAML quality spec file.  These checks measure task correctness, not
structural sanity (which is handled by quality.py).

Spec format — YAML list, one entry per prompt position:

    - contains_all: ["Paris"]        # all phrases must appear (case-insensitive)
      contains_any: ["capital"]      # at least one phrase must appear
      regex: "\\bParis\\b"           # regex applied to stripped text (no implicit flags)
      forbidden: ["I don't know"]    # none of these may appear (case-insensitive)
      min_chars: 10                  # minimum stripped character count
    - null                           # null → skip check for this prompt position

String checks (contains_all, contains_any, forbidden) are case-insensitive.
Prompts with no matching rubric entry are not checked and do not affect the rate.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class TaskRubric:
    contains_all: list[str] = field(default_factory=list)
    contains_any: list[str] = field(default_factory=list)
    regex: str | None = None
    forbidden: list[str] = field(default_factory=list)
    min_chars: int = 0


@dataclass(frozen=True)
class TaskQualityReport:
    task_quality_pass_rate: float
    task_quality_checked_count: int


_VALID_KEYS = {"contains_all", "contains_any", "regex", "forbidden", "min_chars"}


def evaluate_text(text: str, rubric: TaskRubric) -> bool:
    """Return True if *text* passes all rubric checks.

    An empty rubric (all defaults) always passes.
    """
    stripped = text.strip()
    lower = stripped.lower()

    if rubric.min_chars > 0 and len(stripped) < rubric.min_chars:
        return False

    for phrase in rubric.contains_all:
        if phrase.lower() not in lower:
            return False

    if rubric.contains_any and not any(p.lower() in lower for p in rubric.contains_any):
        return False

    for phrase in rubric.forbidden:
        if phrase.lower() in lower:
            return False

    if rubric.regex is not None and not re.search(rubric.regex, stripped):
        return False

    return True


def _parse_rubric(data: Any, index: int, path: str | Path) -> TaskRubric:
    if not isinstance(data, dict):
        raise ValueError(f"{path}: rubric[{index}] must be a mapping, got {type(data).__name__}")
    unknown = set(data.keys()) - _VALID_KEYS
    if unknown:
        raise ValueError(f"{path}: rubric[{index}] has unknown keys: {sorted(unknown)}")
    return TaskRubric(
        contains_all=list(data.get("contains_all") or []),
        contains_any=list(data.get("contains_any") or []),
        regex=data.get("regex"),
        forbidden=list(data.get("forbidden") or []),
        min_chars=int(data.get("min_chars") or 0),
    )


def load_task_rubrics(path: str | Path) -> list[TaskRubric | None]:
    """Load a YAML quality spec and return a list of per-prompt-position rubrics.

    The file must be a YAML list.  Each entry is either a rubric mapping or
    null (to skip checking that prompt position).  If the list is shorter than
    the prompts file, extra prompt positions are not checked.
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, list):
        raise ValueError(f"{path}: quality spec must be a YAML list, got {type(data).__name__}")

    rubrics: list[TaskRubric | None] = []
    for i, entry in enumerate(data):
        if entry is None:
            rubrics.append(None)
        else:
            rubrics.append(_parse_rubric(entry, i, path))
    return rubrics


def compute_task_quality(
    texts: list[str],
    prompt_count: int,
    rubrics: Sequence[TaskRubric | None],
) -> TaskQualityReport:
    """Evaluate completions against per-prompt-position rubrics.

    Args:
        texts: Completion texts from the benchmark loop (warmup excluded).
        prompt_count: Number of unique prompts in the cycling pool.
        rubrics: Per-prompt rubrics indexed by ``i % prompt_count``.
                 None entries and out-of-range positions are skipped.

    Returns:
        TaskQualityReport.  pass_rate is 1.0 when nothing was checked.
    """
    passes = 0
    checked = 0
    for i, text in enumerate(texts):
        prompt_idx = i % prompt_count
        if prompt_idx < len(rubrics) and rubrics[prompt_idx] is not None:
            checked += 1
            rubric = rubrics[prompt_idx]
            assert rubric is not None  # narrowing for type checker
            if evaluate_text(text, rubric):
                passes += 1

    pass_rate = passes / checked if checked > 0 else 1.0
    return TaskQualityReport(
        task_quality_pass_rate=pass_rate,
        task_quality_checked_count=checked,
    )
