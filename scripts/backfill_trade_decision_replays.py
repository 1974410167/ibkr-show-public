#!/usr/bin/env python3
"""Backfill agent_replay and agent_run_id on historical trade decision documents.

For each trade_decision document missing agent_replay or agent_run_id,
look up the matching agent_replay_snapshot by run_id or by
(symbol + agent_name + time proximity) and patch the document.

Usage:
    cd /path/to/ibkr-trade-agent
    cd ibkr_show_backend && ../.venv/bin/python3 ../scripts/backfill_trade_decision_replays.py [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Load .env
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
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


_load_env(_ENV_FILE)

_BACKEND_DIR = _PROJECT_ROOT / "ibkr_show_backend"
sys.path.insert(0, str(_BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.clients.es_client import ElasticsearchClient  # noqa: E402

settings = get_settings()
es = ElasticsearchClient(settings)

TD_INDEX = settings.es_trade_decision_index
REPLAY_INDEX = settings.es_agent_replay_index
TRACE_INDEX = settings.es_agent_run_trace_index


def fetch_decisions_missing_replay(limit: int) -> list[dict]:
    """Find trade decisions missing agent_replay or agent_run_id."""
    resp = es.search(
        index=TD_INDEX,
        body={
            "query": {
                "bool": {
                    "should": [
                        {"bool": {"must_not": {"exists": {"field": "agent_replay.replay_id"}}}},
                        {"bool": {"must_not": {"exists": {"field": "agent_run_id"}}}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "sort": [{"created_at": {"order": "desc"}}],
            "size": limit,
            "_source": True,
        },
    )
    return [hit for hit in resp.get("hits", {}).get("hits", [])]


def find_replay_by_run_id(run_id: str) -> dict | None:
    """Look up replay snapshot by run_id."""
    resp = es.search(
        index=REPLAY_INDEX,
        body={
            "query": {"term": {"run_id": run_id}},
            "size": 1,
        },
    )
    hits = resp.get("hits", {}).get("hits", [])
    return hits[0]["_source"] if hits else None


def find_trace_by_run_id(run_id: str) -> dict | None:
    """Look up agent run trace by run_id."""
    resp = es.search(
        index=TRACE_INDEX,
        body={
            "query": {"term": {"run_id": run_id}},
            "size": 1,
        },
    )
    hits = resp.get("hits", {}).get("hits", [])
    return hits[0]["_source"] if hits else None


def find_replay_by_symbol_time(symbol: str, created_at: str, window_hours: int = 2) -> dict | None:
    """Look up replay snapshot by symbol + time proximity."""
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    start = (dt - timedelta(hours=window_hours)).isoformat()
    end = (dt + timedelta(hours=window_hours)).isoformat()
    resp = es.search(
        index=REPLAY_INDEX,
        body={
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"agent_name": "trade_decision"}},
                        {"range": {"created_at": {"gte": start, "lte": end}}},
                    ]
                }
            },
            "sort": [{"created_at": {"order": "asc"}}],
            "size": 10,
        },
    )
    hits = resp.get("hits", {}).get("hits", [])
    if not hits:
        return None
    # Try to match by request.symbol
    for hit in hits:
        src = hit["_source"]
        req = src.get("request") or {}
        if req.get("symbol") == symbol or req.get("symbol", "").replace(".US", "") == symbol.replace(".US", ""):
            return src
    return hits[0]["_source"]


def backfill(dry_run: bool, limit: int) -> None:
    hits = fetch_decisions_missing_replay(limit)
    print(f"Found {len(hits)} trade decisions missing agent_replay/agent_run_id")
    if not hits:
        return

    patched = 0
    skipped = 0
    for hit in hits:
        doc_id = hit["_id"]
        src = hit["_source"]
        symbol = src.get("symbol", "?")
        created_at = src.get("created_at", "")
        existing_run_id = src.get("agent_run_id")
        existing_replay = src.get("agent_replay") or {}

        # Find matching replay
        replay = None
        run_id = existing_run_id
        if run_id:
            replay = find_replay_by_run_id(run_id)
        if not replay:
            replay = find_replay_by_symbol_time(symbol, created_at)
            if replay:
                run_id = replay.get("run_id")

        if not replay:
            print(f"  SKIP id={doc_id} symbol={symbol} created={created_at[:19]} - no matching replay found")
            skipped += 1
            continue

        replay_id = replay.get("replay_id")
        trace = find_trace_by_run_id(run_id) if run_id else None
        trace_status = trace.get("final_status") if trace else replay.get("final_status")

        update_fields: dict = {}
        if not existing_run_id and run_id:
            update_fields["agent_run_id"] = run_id
        if not existing_replay.get("replay_id") and replay_id:
            update_fields["agent_replay"] = {
                "replay_id": replay_id,
                "run_id": run_id,
                "persisted": True,
                "backfilled": True,
            }
        if run_id and trace_status:
            update_fields["agent_run_trace"] = {
                "run_id": run_id,
                "final_status": trace_status,
            }

        if not update_fields:
            print(f"  SKIP id={doc_id} symbol={symbol} - already has all fields")
            skipped += 1
            continue

        print(f"  PATCH id={doc_id} symbol={symbol} run_id={run_id} replay_id={replay_id}")
        if not dry_run:
            # Use partial update to avoid hitting field limit
            es._client.update(index=TD_INDEX, id=doc_id, body={"doc": update_fields}, refresh=True)
        patched += 1

    print(f"\nDone: {patched} patched, {skipped} skipped (dry_run={dry_run})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill agent_replay on trade decisions")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without applying")
    parser.add_argument("--limit", type=int, default=200, help="Max documents to process")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
