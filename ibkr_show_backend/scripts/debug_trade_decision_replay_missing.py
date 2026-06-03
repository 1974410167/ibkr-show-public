#!/usr/bin/env python3
"""Diagnose why trade_decision replay lookup fails from the frontend."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.clients.es_client import ElasticsearchClient

settings = get_settings()
es = ElasticsearchClient(settings)

TD_INDEX = settings.es_trade_decision_index
REPLAY_INDEX = settings.es_agent_replay_index
TASK_INDEX = settings.es_agent_task_index
TRACE_INDEX = settings.es_agent_run_trace_index

print("=== Trade Decision Replay Debug ===")
print(f"trade_decision_index: {TD_INDEX}")
print(f"agent_replay_index:   {REPLAY_INDEX}")
print(f"agent_task_index:     {TASK_INDEX}")
print(f"agent_run_trace_index:{TRACE_INDEX}")
print()

# --- Recent trade decisions ---
print("--- Recent trade decisions (5) ---")
td_resp = es.search(index=TD_INDEX, body={"sort": [{"created_at": {"order": "desc"}}], "size": 5, "_source": True})
td_hits = td_resp.get("hits", {}).get("hits", [])
for i, hit in enumerate(td_hits, 1):
    src = hit["_source"]
    doc_id = hit["_id"]
    agent_run_id = src.get("agent_run_id")
    meta_run_id = (src.get("metadata") or {}).get("agent_run_id")
    agent_replay = src.get("agent_replay") or {}
    replay_id = agent_replay.get("replay_id")
    replay_persisted = agent_replay.get("persisted")
    replay_run_id = agent_replay.get("run_id")
    symbol = src.get("symbol", "?")
    created = src.get("created_at", "?")[:19]

    print(f"{i}. id={doc_id} symbol={symbol} created={created}")
    print(f"   agent_run_id={agent_run_id}")
    print(f"   metadata.agent_run_id={meta_run_id}")
    print(f"   agent_replay={json.dumps(agent_replay, ensure_ascii=False)[:200]}")

    # Check replay by run_id
    check_id = agent_run_id or meta_run_id
    if check_id:
        by_run = es.search(index=REPLAY_INDEX, body={
            "query": {"term": {"run_id": check_id}},
            "size": 1,
        })
        by_run_hits = by_run.get("hits", {}).get("hits", [])
        print(f"   replay_by_run_id found={len(by_run_hits) > 0}")
        if by_run_hits:
            rsrc = by_run_hits[0]["_source"]
            print(f"     -> replay_id={rsrc.get('replay_id')} final_status={rsrc.get('final_status')}")

    # Check replay by replay_id
    if replay_id:
        try:
            by_id = es.get(index=REPLAY_INDEX, id=replay_id)
            found = by_id is not None
            print(f"   replay_by_id found={found}")
        except Exception as exc:
            print(f"   replay_by_id error={exc}")

    print()

# --- Recent replays ---
print("--- Recent agent_replay snapshots (5) ---")
rp_resp = es.search(index=REPLAY_INDEX, body={
    "query": {"term": {"agent_name": "trade_decision"}},
    "sort": [{"created_at": {"order": "desc"}}],
    "size": 5,
    "_source": True,
})
rp_hits = rp_resp.get("hits", {}).get("hits", [])
for i, hit in enumerate(rp_hits, 1):
    src = hit["_source"]
    print(f"{i}. replay_id={src.get('replay_id')} run_id={src.get('run_id')} status={src.get('final_status')} created={str(src.get('created_at','?'))[:19]}")
print()

# --- Recent tasks ---
print("--- Recent agent tasks (5) ---")
tk_resp = es.search(index=TASK_INDEX, body={
    "query": {"term": {"agent": "trade_decision"}},
    "sort": [{"created_at": {"order": "desc"}}],
    "size": 5,
    "_source": True,
})
tk_hits = tk_resp.get("hits", {}).get("hits", [])
for i, hit in enumerate(tk_hits, 1):
    src = hit["_source"]
    print(f"{i}. id={src.get('id')} status={src.get('status')} result_id={src.get('result_id')} run_id={src.get('run_id')} created={str(src.get('created_at','?'))[:19]}")
print()

# --- Recent traces ---
print("--- Recent agent run traces (5) ---")
tr_resp = es.search(index=TRACE_INDEX, body={
    "query": {"term": {"agent_name": "trade_decision"}},
    "sort": [{"started_at": {"order": "desc"}}],
    "size": 5,
    "_source": ["run_id", "final_status", "started_at", "finished_at", "metadata"],
})
tr_hits = tr_resp.get("hits", {}).get("hits", [])
for i, hit in enumerate(tr_hits, 1):
    src = hit["_source"]
    print(f"{i}. run_id={src.get('run_id')} status={src.get('final_status')} started={str(src.get('started_at','?'))[:19]}")
print()

print("=== Done ===")
