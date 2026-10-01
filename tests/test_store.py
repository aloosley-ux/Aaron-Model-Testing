from pathlib import Path

from aaron_model_testing.store import Store


def test_transient_windows_reader_lock_does_not_lose_artifact_or_index(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.put("runs", {"id": "run", "value": "before"})
    replace = Path.replace
    attempts = 0

    def locked(self, target):
        nonlocal attempts
        if target == tmp_path / "runs/run.json":
            attempts += 1
            if attempts < 3:
                raise PermissionError("Windows reader lock")
        return replace(self, target)

    monkeypatch.setattr(Path, "replace", locked)
    store.put("runs", {"id": "run", "value": "after"})
    assert attempts == 3
    assert store.get("runs", "run")["value"] == "after"
    with store.connection() as db:
        db.execute("DELETE FROM runs")
    assert store.reindex()["runs"] == 1
    assert store.get("runs", "run")["value"] == "after"
