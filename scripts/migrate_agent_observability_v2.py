#!/usr/bin/env python3
"""Migrate agent trace/replay observability documents to v2 ES indices.

The v2 mappings keep large dynamic JSON in _source without expanding it into
Elasticsearch fields. This script copies historical _source documents from the
old trace/replay indices into the configured v2 indices.

Usage:
    cd /path/to/ibkr-trade-agent
    cd ibkr_show_backend && ../.venv/bin/python3 ../scripts/migrate_agent_observability_v2.py --dry-run
    cd ibkr_show_backend && ../.venv/bin/python3 ../scripts/migrate_agent_observability_v2.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from elasticsearch.helpers import scan

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not (key[0].isalpha() or key[0] == "_"):
            continue
        if not all(c.isalnum() or c == "_" for c in key):
            continue
        os.environ.setdefault(key, value.strip().strip("\"'"))


_load_env(_ENV_FILE)
sys.path.insert(0, str(_PROJECT_ROOT / "ibkr_show_backend"))

from app.clients.es_client import ElasticsearchClient  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.services.agent_replay_repository import AGENT_REPLAY_INDEX_BODY  # noqa: E402
from app.services.agent_run_trace_repository import AGENT_RUN_TRACE_INDEX_BODY  # noqa: E402

DEFAULT_REPLAY_V2_INDEX = "ibkr_agent_replay_snapshots_v2"
DEFAULT_TRACE_V2_INDEX = "ibkr_agent_run_traces_v2"


def _copy_index(
    *,
    es: ElasticsearchClient,
    source_index: str,
    target_index: str,
    id_field: str,
    mapping: dict,
    limit: int | None,
    dry_run: bool,
) -> int:
    if dry_run:
        print(f"[dry-run] ensure target index {target_index}")
    else:
        es.create_index_if_missing(target_index, mapping)

    copied = 0
    for hit in scan(es._client, index=source_index, query={"query": {"match_all": {}}}, preserve_order=False):
        document = hit.get("_source") or {}
        doc_id = str(document.get(id_field) or hit.get("_id"))
        copied += 1
        if dry_run:
            if copied <= 5:
                print(f"[dry-run] would copy {source_index}/{doc_id} -> {target_index}/{doc_id}")
        else:
            es.index_document(index=target_index, id=doc_id, document=document)
        if limit is not None and copied >= limit:
            break
    return copied


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print intended copies without writing.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum documents per source index.")
    parser.add_argument("--source-replay-index", default="ibkr_agent_replay_snapshots")
    parser.add_argument("--source-trace-index", default="ibkr_agent_run_traces")
    parser.add_argument("--target-replay-index", default=None)
    parser.add_argument("--target-trace-index", default=None)
    args = parser.parse_args()

    settings = get_settings()
    es = ElasticsearchClient(settings)
    target_replay = args.target_replay_index or settings.es_agent_replay_index
    target_trace = args.target_trace_index or settings.es_agent_run_trace_index
    if target_replay == args.source_replay_index:
        target_replay = DEFAULT_REPLAY_V2_INDEX
    if target_trace == args.source_trace_index:
        target_trace = DEFAULT_TRACE_V2_INDEX

    replay_count = _copy_index(
        es=es,
        source_index=args.source_replay_index,
        target_index=target_replay,
        id_field="replay_id",
        mapping=AGENT_REPLAY_INDEX_BODY,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    trace_count = _copy_index(
        es=es,
        source_index=args.source_trace_index,
        target_index=target_trace,
        id_field="run_id",
        mapping=AGENT_RUN_TRACE_INDEX_BODY,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print(f"replay_copied={replay_count} trace_copied={trace_count} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
