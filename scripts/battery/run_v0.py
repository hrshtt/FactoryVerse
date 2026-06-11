#!/usr/bin/env python
"""Comprehension battery v0 — runner (docs/INFORMATION_SURFACES.md §5).

For each fixture probe: production system prompt + payload + question, one
completion, structured JSON answer. Writes results to
scripts/battery/results/v0_<model>.json. Deterministic scoring where the rule
allows; everything else marked NEEDS-JUDGMENT for human/operator scoring.

Cost note: the system prompt is shared across all probes — after the first
call the prefix is served from provider cache (OBS-2 instrumentation shows
cached_prompt_tokens).
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO / ".env")

FIXTURES = Path(__file__).parent / "fixtures" / "v0.json"
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

MODEL = "anthropic/claude-sonnet-4.6"

PROBE_INSTRUCTION = """You are being probed on your understanding of the
FactoryVerse game interface described in your system prompt. This is NOT a
live game session — do not call tools, do not write code to execute. Read the
provided data, answer the single question, and reply with ONLY the requested
JSON object (no markdown fences, no prose around it)."""


def extract_json(text: str):
    """Best-effort JSON extraction from a model reply."""
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def near(a, b, tol=0.51):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def score(probe, ans):
    """Deterministic scoring where possible. Returns (verdict, note).
    verdict: PASS | FAIL | NEEDS-JUDGMENT | NO-ANSWER"""
    if ans is None:
        return "NO-ANSWER", "reply was not parseable JSON"
    pid, truth = probe["id"], probe["truth"]
    try:
        if pid in ("V1", "V2"):
            p, d = ans.get("pickup") or {}, ans.get("drop") or {}
            ok = (near(p.get("x"), truth["pickup"]["x"]) and near(p.get("y"), truth["pickup"]["y"])
                  and near(d.get("x"), truth["drop"]["x"]) and near(d.get("y"), truth["drop"]["y"]))
            return ("PASS" if ok else "FAIL"), f"engine pickup={truth['pickup']} drop={truth['drop']}"
        if pid == "V3":
            return ("PASS" if ans.get("connects") is False else "FAIL"), ""
        if pid == "V4":
            ok = "power" in json.dumps(ans).lower()
            return ("PASS" if ok and ans.get("meaning") and "no" in str(ans.get("meaning")).lower() else "NEEDS-JUDGMENT"), ""
        if pid == "V6":
            forb = ans.get("forbidden") or []
            tp, td = truth["pickup"], truth["drop"]
            def covered(cell):
                return any(near(f.get("x"), cell["x"], 1.01) and near(f.get("y"), cell["y"], 1.01)
                           for f in forb if isinstance(f, dict))
            ok = covered(tp) and covered(td)
            return ("PASS" if ok else "FAIL"), f"must cover pickup={tp} drop={td}; got {forb}"
        if pid == "V8":
            return ("PASS" if ans.get("n_placements") == 1 else "FAIL"), f"side={ans.get('side','')[:120]}"
        if pid == "V9":
            return ("PASS" if ans.get("possible") is False else "FAIL"), str(ans.get("why", ""))[:120]
        if pid == "V11":
            return ("PASS" if ans.get("broken") is False else "FAIL"), str(ans.get("explanation", ""))[:120]
        if pid == "V12":
            return ("PASS" if ans.get("continues") is False else "FAIL"), str(ans.get("evidence_field", ""))[:80]
        if pid == "V13":
            nx = ans.get("next_cell") or {}
            ok = (ans.get("continues") is True and near(nx.get("x"), truth["next"]["x"])
                  and near(nx.get("y"), truth["next"]["y"]))
            return ("PASS" if ok else "FAIL"), f"engine next={truth['next']}"
        if pid == "V14":
            return ("PASS" if ans.get("sufficient") is False
                    and "coal" in json.dumps(ans).lower() else "NEEDS-JUDGMENT"), ""
        if pid == "V15":
            steps = json.dumps(ans.get("steps", [])).lower()
            ok = ("boiler" in steps or "fuel" in steps or "generator" in steps or "engine" in steps)
            return ("PASS" if ok else "FAIL"), "must walk generator side"
        if pid == "V16":
            build = json.dumps(ans).lower()
            ok = ans.get("recurring") is True and "boiler" in build and ("inserter" in build or "belt" in build or "drill" in build)
            return ("PASS" if ok else "FAIL"), str(ans.get("build", ""))[:120]
        if pid == "V18":
            n = ans.get("networks")
            distinct = len(truth["engine_networks"])
            return ("PASS" if n == distinct else "FAIL"), f"engine distinct nets={distinct}"
        if pid == "V19":
            return ("PASS" if ans.get("trust") is False else "FAIL"), str(ans.get("check", ""))[:120]
        if pid == "V20":
            sql = str(ans.get("sql", "")).lower()
            return ("PASS" if "chunk_snapshot_meta" in sql else "FAIL"), sql[:120]
        if pid == "V21":
            return ("PASS" if ans.get("functional_now") is False else "FAIL"), str(ans.get("what_needed", ""))[:100]
        if pid == "V22":
            sql = str(ans.get("sql", "")).lower()
            uses_dead = ("from inserter" in sql or "join inserter" in sql)
            return ("RECORD", f"uses_dead_table={uses_dead} sql={sql[:160]}")
        if pid == "V23":
            tiles = ans.get("tiles") or []
            bb = truth["bb"]
            import math
            want = {(tx, ty)
                    for tx in range(math.floor(bb["left_top"]["x"]), math.ceil(bb["right_bottom"]["x"]))
                    for ty in range(math.floor(bb["left_top"]["y"]), math.ceil(bb["right_bottom"]["y"]))}
            got = {(int(t.get("x")), int(t.get("y"))) for t in tiles if isinstance(t, dict)}
            return ("PASS" if got == want else "FAIL"), f"want {sorted(want)} got {sorted(got)}"
        if pid == "V24":
            return ("PASS" if ans.get("can_place") is False else "FAIL"), str(ans.get("first_action", ""))[:80]
        if pid in ("V5", "V10", "V25"):
            return "NEEDS-JUDGMENT", ""
    except Exception as e:  # noqa: BLE001
        return "NEEDS-JUDGMENT", f"scorer error: {e}"
    return "NEEDS-JUDGMENT", ""


def main():
    from FactoryVerse.infra.llm.client.factory import create_prime_intellect_client
    from FactoryVerse.infra.llm.prompts.system_prompt import generate_system_prompt

    probes = json.loads(FIXTURES.read_text())
    system_prompt = generate_system_prompt()
    client = create_prime_intellect_client(model=MODEL)

    results = []
    tally = {"PASS": 0, "FAIL": 0, "NEEDS-JUDGMENT": 0, "NO-ANSWER": 0, "RECORD": 0}
    total_cached = total_prompt = 0
    for probe in probes:
        user = (PROBE_INSTRUCTION + "\n\n=== DATA ===\n" + probe["payload"]
                + "\n\n=== QUESTION ===\n" + probe["question"])
        r = client.chat_completion(
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user}],
            temperature=0.0, max_tokens=700)
        text = r.message.content or ""
        ans = extract_json(text)
        verdict, note = score(probe, ans)
        tally[verdict] = tally.get(verdict, 0) + 1
        u = r.usage
        if u:
            total_prompt += u.prompt_tokens
            total_cached += u.cached_prompt_tokens or 0
        results.append({"id": probe["id"], "concept": probe["concept"],
                        "verdict": verdict, "note": note,
                        "answer": ans, "raw": text[:1200],
                        "truth": probe["truth"],
                        "scoring_rule": probe["scoring"]})
        print(f"{probe['id']:4s} {probe['concept']:20s} {verdict:15s} {note[:90]}")
        time.sleep(1)

    out = RESULTS_DIR / f"v0_{MODEL.split('/')[-1]}.json"
    out.write_text(json.dumps({"model": MODEL, "tally": tally,
                               "prompt_tokens": total_prompt,
                               "cached_tokens": total_cached,
                               "results": results}, indent=1))
    print(f"\ntally: {tally}")
    print(f"tokens: {total_prompt:,} prompt, {total_cached:,} cached "
          f"({100*total_cached/max(total_prompt,1):.0f}%)")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
