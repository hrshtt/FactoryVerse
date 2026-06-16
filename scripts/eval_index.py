#!/usr/bin/env python3
"""Build/refresh the eval-trajectory DuckDB index.

Usage:
    uv run python scripts/eval_index.py [--evals-dir .fv-output/evals] [--db PATH]

Walks all run dirs under .fv-output/evals/{task}/{run_id}/ and indexes
trajectory.jsonl + config.json into .fv-output/evals/evals.duckdb so that
failure attribution is a SQL query instead of re-reading JSONL.

Tables (full drop+recreate on every invocation — idempotent):
    runs        one row per run dir (config + session_start/run_start +
                run_end outcome + verification + aggregates)
    events      every trajectory event (payload preserved as JSON)
    tool_calls  paired tool_start/tool_code/tool_result with duration and
                mechanical error classification
    errors      every error occurrence (failed/error-text tool results and
                explicit error events) with classified kind

Views:
    v_runs_summary         compact per-run overview
    v_error_kind_by_task   error frequency by classified kind per task
    v_tool_calls_per_run   tool-call / error counts per run
    v_tool_calls_per_turn  turn-by-turn tool-call counts

Notes on real-world data (vs trajectory.py's EventType enum):
    - `run_start` events exist on disk but are NOT in the EventType enum.
    - `tool_result.success` is unreliable (often true despite "Error: ..."
      text), so error detection is regex-based on the result text.
    - Most runs never wrote run_end/session_end/turn_complete/
      assistant_response; aggregates are derived from raw events instead.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import duckdb

# ---------------------------------------------------------------------------
# Error classification (mechanical, ordered: first match wins)
# ---------------------------------------------------------------------------

ERROR_KIND_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # Domain-specific first, so e.g. a place_entity RCON/Lua error counts as
    # a placement failure rather than a generic lua traceback.
    ("placement_failure", re.compile(r"place_entity|can_place|placement.*(fail|invalid)|(fail|invalid).*placement", re.I)),
    ("walking_error", re.compile(r"WalkingUnreachableError|Walking failed|walk.*unreachable", re.I)),
    ("lua_traceback", re.compile(r"Error when running interface function|stack traceback|__fv_embodied_agent|\.lua:\d+")),
    ("api_4xx", re.compile(r"\b4\d\d\b.*(Bad Request|Unauthorized|Forbidden|Not Found|Too Many)|HTTP.*\b4\d\d\b|status[ _]?code[=: ]+4\d\d", re.I)),
    ("sql_error", re.compile(r"Catalog Error|Binder Error|Parser Error|Conversion Error|duckdb\.\w*Error")),
    ("attribute_error", re.compile(r"\bAttributeError\b")),
    ("name_error", re.compile(r"\bNameError\b")),
    ("type_error", re.compile(r"\bTypeError\b")),
    ("import_error", re.compile(r"\bModuleNotFoundError\b|\bImportError\b")),
    ("index_key_error", re.compile(r"\bIndexError\b|\bKeyError\b")),
    ("value_error", re.compile(r"\bValueError\b")),
    ("timeout", re.compile(r"\bTimeoutError\b|timed? ?out", re.I)),
    ("runtime_error", re.compile(r"\bRuntimeError\b")),
]

ERROR_TEXT_RE = re.compile(r"^\s*(Error:|❌|Traceback \(most recent call last\))")


def classify_error(text: str) -> str:
    for kind, pat in ERROR_KIND_PATTERNS:
        if pat.search(text):
            return kind
    return "other"


def is_error_result(result: Optional[str], success: Any) -> bool:
    if success is False:
        return True
    if result and ERROR_TEXT_RE.match(result):
        return True
    return False


# ---------------------------------------------------------------------------
# Run-dir parsing
# ---------------------------------------------------------------------------

def iter_run_dirs(evals_dir: Path) -> Iterator[Tuple[str, str, Path]]:
    """Yield (task, run_id, run_dir) for every run dir with a trajectory."""
    for task_dir in sorted(p for p in evals_dir.iterdir() if p.is_dir()):
        for run_dir in sorted(p for p in task_dir.iterdir() if p.is_dir()):
            if (run_dir / "trajectory.jsonl").exists() or (run_dir / "config.json").exists():
                yield task_dir.name, run_dir.name, run_dir


def read_events(trajectory_path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    if not trajectory_path.exists():
        return events
    with open(trajectory_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip malformed lines, same as TrajectoryReader
    return events


def excerpt(text: Optional[str], limit: int = 500) -> Optional[str]:
    if text is None:
        return None
    return text if len(text) <= limit else text[:limit] + "…"


def index_run(task: str, run_id: str, run_dir: Path) -> Dict[str, Any]:
    """Parse one run dir into row dicts for all tables."""
    run_key = f"{task}/{run_id}"

    config: Dict[str, Any] = {}
    config_path = run_dir / "config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    events = read_events(run_dir / "trajectory.jsonl")

    event_rows: List[Tuple] = []
    tool_call_rows: List[Tuple] = []
    error_rows: List[Tuple] = []

    # run-level accumulators
    model = mode = scenario = agent_id = None
    started_ts: Optional[float] = None
    ended_ts: Optional[float] = None
    run_end: Optional[Dict[str, Any]] = None
    prompt_tokens = completion_tokens = total_tokens = 0
    max_turn: Optional[int] = None
    last_verification: Optional[Dict[str, Any]] = None
    verification_checks = 0
    verification_passes = 0

    pending: Optional[Dict[str, Any]] = None  # open tool call
    call_index = 0

    def flush_pending() -> None:
        nonlocal pending, call_index
        if pending is None:
            return
        p = pending
        result = p.get("result")
        err = is_error_result(result, p.get("success"))
        kind = classify_error(result) if (err and result) else (None if not err else "other")
        duration = (
            round(p["end_ts"] - p["start_ts"], 3)
            if p.get("end_ts") is not None and p.get("start_ts") is not None
            else None
        )
        tool_call_rows.append((
            run_key, call_index, p.get("seq"), p.get("turn"), p.get("tool"),
            p.get("iteration"), p.get("lang"), p.get("code"),
            excerpt(result), err, kind, duration,
            p.get("end_ts") is not None,
        ))
        if err:
            error_rows.append((
                run_key, p.get("turn"), p.get("seq"), "tool_result",
                excerpt(result, 1000), kind or "other",
            ))
        call_index += 1
        pending = None

    for seq, ev in enumerate(events):
        etype = ev.get("type")
        ts = ev.get("ts")
        turn = ev.get("turn")
        tick = ev.get("game_tick")
        payload = {k: v for k, v in ev.items() if k not in ("type", "ts")}
        event_rows.append((run_key, seq, etype, ts, turn, tick, json.dumps(payload)))

        if ts is not None:
            started_ts = ts if started_ts is None else min(started_ts, ts)
            ended_ts = ts if ended_ts is None else max(ended_ts, ts)
        if turn is not None:
            max_turn = turn if max_turn is None else max(max_turn, turn)

        if etype == "run_start":
            scenario = ev.get("scenario", scenario)
            agent_id = ev.get("agent_id", agent_id)
        elif etype == "session_start":
            model = ev.get("model", model)
            mode = ev.get("mode", mode)
        elif etype == "completion_stats":
            usage = ev.get("usage") or {}
            prompt_tokens += usage.get("prompt_tokens", 0)
            completion_tokens += usage.get("completion_tokens", 0)
            total_tokens += usage.get("total_tokens", 0)
        elif etype == "tool_start":
            flush_pending()  # dangling tool_start without a result
            pending = {
                "seq": seq, "turn": turn, "tool": ev.get("tool"),
                "iteration": ev.get("iteration"), "start_ts": ts,
                "code": None, "lang": None, "result": None,
                "success": None, "end_ts": None,
            }
        elif etype == "tool_code":
            if pending is not None:
                pending["code"] = ev.get("code")
                pending["lang"] = ev.get("lang")
        elif etype == "tool_result":
            if pending is not None:
                pending["result"] = ev.get("result")
                pending["success"] = ev.get("success", True)
                pending["end_ts"] = ts
                flush_pending()
            else:
                # orphan result: still scan for errors
                result = ev.get("result")
                if is_error_result(result, ev.get("success")):
                    error_rows.append((
                        run_key, turn, seq, "tool_result",
                        excerpt(result, 1000), classify_error(result or ""),
                    ))
        elif etype == "error":
            msg = ev.get("message") or ""
            error_rows.append((
                run_key, turn, seq, "error_event",
                excerpt(msg, 1000), classify_error(msg),
            ))
        elif etype == "verification_check":
            verification_checks += 1
            if ev.get("passed"):
                verification_passes += 1
            last_verification = ev
        elif etype == "run_end":
            run_end = ev

    flush_pending()

    verification = (run_end or {}).get("verification") or {}
    # Fall back to last verification_check if run_end never written.
    v_current_rate = verification.get("current_rate")
    v_target_rate = verification.get("target_rate")
    v_automation = verification.get("automation_produced")
    if last_verification is not None:
        if v_current_rate is None:
            v_current_rate = last_verification.get("current_rate")
        if v_target_rate is None:
            v_target_rate = last_verification.get("target_rate")
        if v_automation is None:
            v_automation = last_verification.get("automation_produced")

    run_row = (
        run_key, run_id, task,
        config.get("agent_id", agent_id), scenario or config.get("scenario"),
        config.get("variant"), model, mode,
        config.get("started_at"), started_ts, ended_ts,
        round(ended_ts - started_ts, 3) if started_ts is not None and ended_ts is not None else None,
        (run_end or {}).get("success"),
        run_end is not None,
        (max_turn + 1) if max_turn is not None else 0,  # turns are 0-indexed
        len([r for r in tool_call_rows]),
        len(error_rows),
        len(events),
        prompt_tokens, completion_tokens, total_tokens,
        verification_checks, verification_passes,
        v_current_rate, v_target_rate, v_automation,
        verification.get("failure_reason"),
        verification.get("measured_at_tick"),
        (run_end or {}).get("error"),
        str(run_dir),
    )

    return {
        "run": run_row,
        "events": event_rows,
        "tool_calls": tool_call_rows,
        "errors": error_rows,
    }


# ---------------------------------------------------------------------------
# DB build
# ---------------------------------------------------------------------------

SCHEMA = """
DROP TABLE IF EXISTS errors;
DROP TABLE IF EXISTS tool_calls;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS runs;

CREATE TABLE runs (
    run_key            VARCHAR PRIMARY KEY,   -- task/run_id
    run_id             VARCHAR,
    task               VARCHAR,
    agent_id           VARCHAR,
    scenario           VARCHAR,
    variant            VARCHAR,
    model              VARCHAR,
    mode               VARCHAR,
    started_at         VARCHAR,               -- config.json ISO timestamp
    first_event_ts     DOUBLE,
    last_event_ts      DOUBLE,
    duration_s         DOUBLE,
    success            BOOLEAN,               -- from run_end; NULL if absent
    has_run_end        BOOLEAN,
    total_turns        INTEGER,
    total_tool_calls   INTEGER,
    total_errors       INTEGER,
    total_events       INTEGER,
    prompt_tokens      BIGINT,
    completion_tokens  BIGINT,
    total_tokens       BIGINT,
    verification_checks  INTEGER,
    verification_passes  INTEGER,
    verif_current_rate   DOUBLE,
    verif_target_rate    DOUBLE,
    verif_automation_produced BIGINT,
    verif_failure_reason VARCHAR,
    verif_measured_at_tick BIGINT,
    run_end_error      VARCHAR,
    run_dir            VARCHAR
);

CREATE TABLE events (
    run_key    VARCHAR,
    seq        INTEGER,   -- line order within trajectory.jsonl
    event_type VARCHAR,
    ts         DOUBLE,
    turn       INTEGER,
    tick       BIGINT,    -- game_tick where present (verification_check)
    payload    JSON       -- full event minus type/ts
);

CREATE TABLE tool_calls (
    run_key        VARCHAR,
    call_index     INTEGER,  -- 0-based per run
    seq            INTEGER,  -- seq of the tool_start event
    turn           INTEGER,
    tool           VARCHAR,
    iteration      INTEGER,
    lang           VARCHAR,
    code           VARCHAR,
    result_excerpt VARCHAR,  -- first 500 chars
    is_error       BOOLEAN,
    error_kind     VARCHAR,
    duration_s     DOUBLE,   -- tool_result.ts - tool_start.ts
    completed      BOOLEAN   -- false for dangling tool_start without result
);

CREATE TABLE errors (
    run_key    VARCHAR,
    turn       INTEGER,
    seq        INTEGER,
    source     VARCHAR,   -- tool_result | error_event
    error_text VARCHAR,   -- first 1000 chars
    kind       VARCHAR
);
"""

VIEWS = """
CREATE OR REPLACE VIEW v_runs_summary AS
SELECT task, run_id, model, scenario, success, has_run_end,
       total_turns, total_tool_calls, total_errors,
       total_tokens, round(duration_s, 1) AS duration_s,
       verif_current_rate, verif_target_rate, verif_failure_reason
FROM runs
ORDER BY task, run_id;

CREATE OR REPLACE VIEW v_error_kind_by_task AS
SELECT r.task, e.kind, count(*) AS n,
       count(DISTINCT e.run_key) AS runs_affected
FROM errors e JOIN runs r USING (run_key)
GROUP BY r.task, e.kind
ORDER BY r.task, n DESC;

CREATE OR REPLACE VIEW v_tool_calls_per_run AS
SELECT r.task, r.run_id, count(t.run_key) AS tool_calls,
       coalesce(sum(CASE WHEN t.is_error THEN 1 ELSE 0 END), 0) AS errored,
       round(avg(t.duration_s), 2) AS avg_duration_s
FROM runs r LEFT JOIN tool_calls t USING (run_key)
GROUP BY r.task, r.run_id
ORDER BY r.task, r.run_id;

CREATE OR REPLACE VIEW v_tool_calls_per_turn AS
SELECT run_key, turn, count(*) AS tool_calls,
       sum(CASE WHEN is_error THEN 1 ELSE 0 END) AS errored
FROM tool_calls
GROUP BY run_key, turn
ORDER BY run_key, turn;
"""


def build(evals_dir: Path, db_path: Path) -> Dict[str, int]:
    runs = list(iter_run_dirs(evals_dir))
    if not runs:
        print(f"No run dirs found under {evals_dir}", file=sys.stderr)
        sys.exit(1)

    con = duckdb.connect(str(db_path))
    con.execute("BEGIN")
    con.execute(SCHEMA)

    for task, run_id, run_dir in runs:
        parsed = index_run(task, run_id, run_dir)
        con.execute(
            f"INSERT INTO runs VALUES ({','.join('?' * 30)})", parsed["run"]
        )
        if parsed["events"]:
            con.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?)", parsed["events"])
        if parsed["tool_calls"]:
            con.executemany(
                "INSERT INTO tool_calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                parsed["tool_calls"],
            )
        if parsed["errors"]:
            con.executemany("INSERT INTO errors VALUES (?,?,?,?,?,?)", parsed["errors"])

    con.execute(VIEWS)
    con.execute("COMMIT")

    counts = {
        t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ("runs", "events", "tool_calls", "errors")
    }
    con.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    repo_root = Path(__file__).resolve().parent.parent
    parser.add_argument(
        "--evals-dir", type=Path, default=repo_root / ".fv-output" / "evals",
        help="Directory containing {task}/{run_id}/ run dirs",
    )
    parser.add_argument(
        "--db", type=Path, default=None,
        help="Output DuckDB path (default: <evals-dir>/evals.duckdb)",
    )
    args = parser.parse_args()

    evals_dir = args.evals_dir
    db_path = args.db or (evals_dir / "evals.duckdb")
    counts = build(evals_dir, db_path)

    print(f"Built {db_path}")
    for table, n in counts.items():
        print(f"  {table:<11} {n:>6} rows")


if __name__ == "__main__":
    main()
