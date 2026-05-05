from pathlib import Path

from worker.jobs.import_daily_snapshot import import_daily_snapshot_file


class StubStatement:
    def documents_by_index(self) -> dict[str, list[dict]]:
        return {
            "account-index": [{"_id": "doc-1", "account_id": "U1"}],
            "trade-index": [{"_id": "doc-2", "account_id": "U1"}],
        }


class StubESWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict]]] = []

    def bulk_upsert(self, index_name: str, documents: list[dict]) -> dict:
        self.calls.append((index_name, documents))
        return {"index": index_name, "upserted": len(documents)}


class StubCacheInvalidator:
    def __init__(self, _settings) -> None:
        self.clear_calls = 0

    def clear_all(self) -> int:
        self.clear_calls += 1
        return 2


def test_import_daily_snapshot_file_clears_cache_after_success(monkeypatch) -> None:
    cache_invalidator = StubCacheInvalidator(None)
    monkeypatch.setattr(
        "worker.jobs.import_daily_snapshot.parse_flex_csv",
        lambda file_path: {"file_path": str(file_path)},
    )
    monkeypatch.setattr(
        "worker.jobs.import_daily_snapshot.transform_daily_statement",
        lambda statement: StubStatement(),
    )
    monkeypatch.setattr(
        "worker.jobs.import_daily_snapshot.RedisCacheInvalidator",
        lambda settings: cache_invalidator,
    )

    es_writer = StubESWriter()
    result = import_daily_snapshot_file(es_writer, Path("/tmp/fake.csv"))

    assert result == {
        "account-index": {"index": "account-index", "upserted": 1},
        "trade-index": {"index": "trade-index", "upserted": 1},
    }
    assert [call[0] for call in es_writer.calls] == ["account-index", "trade-index"]
    assert cache_invalidator.clear_calls == 1
