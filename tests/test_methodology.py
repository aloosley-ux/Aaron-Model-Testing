import shutil
from types import SimpleNamespace

import pytest

from aaron_model_testing import suite as suite_module
from aaron_model_testing.longcontext import KINDS, build_case
from aaron_model_testing.performance import distribution, summarize
from aaron_model_testing.profiles import RuntimeConfig
from aaron_model_testing.tuning import candidates, objective


def test_statistics_do_not_hide_failed_samples():
    assert distribution([1, 2, 3])["variance"] == 1
    assert distribution([1])["variance"] is None
    records = [
        {"type": "performance", "success": True, "metrics": {"generation_tps": n}, "context_size": 1024}
        for n in [1, 2, 3]
    ]
    records.append({"type": "performance", "success": False, "error": "OOM", "context_size": 4096})
    result = summarize(records)
    assert result["reliability"] == 0.75
    assert result["metrics"]["generation_tps"]["median"] == 2
    assert result["contexts"]["4096"]["generation_tps"]["median"] is None
    assert objective(result, "FAST") is None


def test_tuning_breadth_drill_and_fixed_context():
    base = RuntimeConfig(ctx_size=8192)
    for preset in ["quick", "standard", "thorough", "drill"]:
        values = candidates(base, preset, 24)
        assert 2 <= len(values) <= 24  # Budget is a cap; a small preset may have fewer unique candidates.
        assert all(v.ctx_size == 8192 for v in values)
        assert len({v.model_dump_json() for v in values}) == len(values)
        assert any(v.gpu_layers != base.gpu_layers for v in values)
        assert any(v.flash_attn != base.flash_attn for v in values)
        assert any(v.batch_size != base.batch_size for v in values)


class TokenServer:
    config = SimpleNamespace(ctx_size=4096)

    def render(self, messages):
        return "\n".join(m["content"] for m in messages)

    def tokenize(self, text):
        return text.split()


@pytest.mark.parametrize("kind", KINDS)
def test_long_context_determinism_token_budget_and_actual_depths(kind):
    a = build_case(kind, 2048, 0.5, 42, TokenServer(), 512)
    b = build_case(kind, 2048, 0.5, 42, TokenServer(), 512)
    assert a == b
    assert 2000 <= a["input_tokens_measured"] <= 2048
    assert a["rule"]["expected"]
    assert all(0 <= p["actual_token_depth"] <= 1 for p in a["insertion_positions"])
    assert abs(a["insertion_positions"][0]["actual_token_depth"] - 0.5) < 0.1


def test_immutable_version_detects_scoring_changes(tmp_path, monkeypatch):
    root = suite_module.ROOT
    for relative in suite_module.load_suite()[1]["files"]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
    shutil.copyfile(root / "benchmarks/versions.lock.json", tmp_path / "benchmarks/versions.lock.json")
    monkeypatch.setattr(suite_module, "ROOT", tmp_path)
    assert suite_module.load_suite()[0]["id"] == "agent-core-v1"
    with (tmp_path / "scoring.py").open("a") as f:
        f.write("\n# accidental change\n")
    with pytest.raises(ValueError, match="Immutable benchmark version changed"):
        suite_module.load_suite()
