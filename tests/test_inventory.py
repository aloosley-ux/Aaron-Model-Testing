from pathlib import Path

import numpy as np
import pytest
from gguf import GGUFWriter

from aaron_model_testing.inventory import discover, json_metadata, register, shards, verify_model
from aaron_model_testing.util import file_hash


def tiny_gguf(path: Path):
    writer = GGUFWriter(path, "llama")
    writer.add_string("general.name", "Tiny test model")
    writer.add_uint32("llama.context_length", 4096)
    writer.add_string("tokenizer.chat_template", "{{ messages }}")
    writer.add_tensor("test.weight", np.zeros((4, 4), dtype=np.float32))
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()


def test_header_and_full_hash_with_windows_spaces(tmp_path):
    path = tmp_path / "model with spaces-Q4_K_M.gguf"
    tiny_gguf(path)
    model = register(path)
    assert model["sha256"] == file_hash(path)
    assert model["parameter_count"] == 16
    assert model["context_capability"] == 4096
    assert model["architecture"] == "llama"
    assert model["quantisation"] == "Q4_K_M"
    assert model["chat_template"] == "{{ messages }}"
    assert discover([str(tmp_path), str(path)]) == [path]
    verify_model(model)
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="fingerprint changed"):
        verify_model(model)


def test_split_fingerprint_contains_every_shard(tmp_path):
    paths = [tmp_path / f"model-0000{i}-of-00002.gguf" for i in (1, 2)]
    for path in paths:
        tiny_gguf(path)
    assert shards(paths[1]) == paths
    model = register(paths[1])
    assert len(model["files"]) == 2
    assert model["parameter_count"] == 32
    assert model["path"] == str(paths[0])
    paths[1].unlink()
    with pytest.raises(ValueError, match="incomplete"):
        shards(paths[0])


def test_auxiliary_and_bad_roots(tmp_path):
    path = tmp_path / "mmproj-tiny.gguf"
    tiny_gguf(path)
    assert register(path)["status"] == "auxiliary"
    with pytest.raises(ValueError, match="does not exist"):
        discover([str(tmp_path / "missing")])
    assert json_metadata([float("-inf"), 1.0]) == [{"non_finite_float": "-inf"}, 1.0]
