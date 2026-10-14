#!/usr/bin/env python3
"""Path E measurement: run the A-matched and D-matched protocols against Foundry Prompt Agent + E2B on Azure VM.

    python tools/measure_e2b.py agent --runs 3
    python tools/measure_e2b.py perf  --cold 5 --warm-turns 3 --scale 4,8 --recovery

agent mode, per run: Sandbox.create("base") -> first Prompt Agent answer ("Where is Bangkok? Answer in one short
sentence.") -> follow-up ("How many questions have I asked before this one? Number only.") -> beta_pause -> wait
5 s -> Sandbox.connect -> follow-up -> follow-up -> kill, verifying that sandbox conversation history grows 1..4
across pause and resume.
perf mode: cold new sessions ("Reply with exactly COLD-{i}"), warm follow-ups with "LANTERN-7", concurrent
new sessions ("Remember SCALE-{i}. Reply only OK." -> "What did I ask you to remember? Word only."), and
sandbox replacement after kill.

Reads PROJECT_ENDPOINT, E2B_API_URL, E2B_SANDBOX_URL and ACA_MODEL from the environment (.env). Writes
evidence-local/e2b-<mode>-<UTC time>.json. Exit codes: 0 all requested phases passed, 1 a run failed or
lost state, 2 a required setting is missing or arguments are invalid.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIRST_Q = "Where is Bangkok? Answer in one short sentence."
COUNT_Q = "How many questions have I asked before this one? Number only."
COLD_INPUT = "Reply with exactly COLD-{i}"
WARM_FIRST = "Remember the code word LANTERN-7. Reply only OK."
WARM_RECALL = "What is the code word? Reply with the word only."
WARM_NEXT = "Reply with exactly WARM-{i}"
SCALE_T1 = "Remember SCALE-{i}. Reply only OK."
SCALE_T2 = "What did I ask you to remember? Word only."


class SettingMissing(RuntimeError):
    pass


def need_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val or val.startswith("YOUR-"):
        raise SettingMissing(f"missing or placeholder environment variable: {name}")
    return val


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def utc_hms() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def token() -> str:
    out = subprocess.run(
        ["az", "account", "get-access-token", "--resource", "https://ai.azure.com", "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"az account get-access-token failed: {out.stderr.strip()}")
    return out.stdout.strip()


def load_sandbox_cls():
    try:
        from e2b import Sandbox
        return Sandbox
    except ImportError as exc:
        raise RuntimeError("Install e2b SDK first: pip install e2b") from exc


def foundry_req(endpoint: str, method: str, path: str, tok: str, body: dict | None = None, timeout: int = 180) -> dict:
    url = f"{endpoint.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}


def extract_text(resp_doc: dict) -> str:
    parts = []
    for item in resp_doc.get("output", []) or []:
        if item.get("type") == "message":
            for c in item.get("content", []) or []:
                if c.get("type") in ("output_text", "text") and c.get("text"):
                    parts.append(c["text"])
    return " ".join(parts).strip()


def sandbox_exec_python(sbx, code: str, question: str) -> dict:
    wrapper = (
        "import json, os, platform\n"
        "p = os.path.expanduser('~/history.json')\n"
        "h = json.load(open(p)) if os.path.exists(p) else []\n"
        "prior_count = len(h)\n"
        f"h.append({{'turn': prior_count + 1, 'question': {question!r}}})\n"
        "json.dump(h, open(p, 'w'))\n"
        "ns = {'prior_questions': prior_count, 'history_length': len(h)}\n"
        f"exec({code!r}, ns)\n"
        "print('__STATE__=' + json.dumps({'prior_questions': prior_count, 'history_length': len(h), 'kernel': platform.release()}))\n"
    )
    t0 = time.perf_counter()
    res = sbx.commands.run(f"python3 - <<'PY'\n{wrapper}\nPY", timeout=60)
    elapsed = round(time.perf_counter() - t0, 3)
    if getattr(res, "exit_code", 0) != 0:
        raise RuntimeError(f"sandbox python exit {res.exit_code}: {getattr(res, 'stderr', '') or res.stdout}")
    lines = [ln for ln in (res.stdout or "").strip().splitlines() if ln.strip()]
    state_line = next((ln[len("__STATE__="):] for ln in reversed(lines) if ln.startswith("__STATE__=")), "{}")
    user_lines = [ln for ln in lines if not ln.startswith("__STATE__=")]
    return {"exec_s": elapsed, "stdout": "\n".join(user_lines).strip(), "state": json.loads(state_line)}


def ask_agent(endpoint: str, tok: str, agent_name: str, agent_ver: str, conv_id: str, sbx, question: str) -> dict:
    t_start = time.perf_counter()
    started = utc_hms()
    body = {
        "conversation": conv_id,
        "input": [{"type": "message", "role": "user", "content": question}],
        "agent_reference": {"type": "agent_reference", "name": agent_name, "version": str(agent_ver)},
    }
    resp = foundry_req(endpoint, "POST", "/openai/v1/responses", tok, body)
    tool_s_total = 0.0
    last_state: dict = {}
    while True:
        fn_calls = [item for item in resp.get("output", []) if item.get("type") == "function_call"]
        if not fn_calls:
            break
        outputs = []
        for call in fn_calls:
            args = json.loads(call.get("arguments") or "{}")
            exec_info = sandbox_exec_python(sbx, args.get("python_code", "print('ok')"), question)
            tool_s_total += exec_info["exec_s"]
            last_state = exec_info["state"]
            outputs.append({
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": json.dumps({
                    "stdout": exec_info["stdout"],
                    "prior_questions_in_sandbox": last_state.get("prior_questions"),
                    "history_length_in_sandbox": last_state.get("history_length"),
                }, ensure_ascii=False),
            })
        resp = foundry_req(endpoint, "POST", "/openai/v1/responses", tok, {
            "conversation": conv_id, "input": outputs,
            "agent_reference": {"type": "agent_reference", "name": agent_name, "version": str(agent_ver)},
        })
    ans = extract_text(resp)
    if not ans:
        raise RuntimeError(f"non-empty answer missing for {question!r}")
    return {
        "started_utc": started, "http": 200, "guest_s": round(time.perf_counter() - t_start, 2),
        "sandbox_tool_s": round(tool_s_total, 3), "response": ans,
        "history_length": last_state.get("history_length", 0),
    }


def agent_run(endpoint: str, tok: str, agent_name: str, agent_ver: str, template: str, index: int, sandbox_cls=None) -> dict:
    Sandbox = sandbox_cls or load_sandbox_cls()
    rec: dict = {"run": index, "started_at": now_iso(), "vmm_type": "firecracker"}
    sbx = None
    conv_id = None
    try:
        conv_id = foundry_req(endpoint, "POST", "/openai/v1/conversations", tok, {})["id"]
        t0 = time.perf_counter()
        sbx = Sandbox.create(template, timeout=300)
        rec["create_total_s"] = round(time.perf_counter() - t0, 2)
        sbx_id = sbx.sandbox_id
        rec["first"] = ask_agent(endpoint, tok, agent_name, agent_ver, conv_id, sbx, FIRST_Q)
        rec["cold_total_s"] = round(rec["create_total_s"] + rec["first"]["guest_s"], 2)
        rec["warm"] = ask_agent(endpoint, tok, agent_name, agent_ver, conv_id, sbx, COUNT_Q)
        t1 = time.perf_counter()
        sbx.beta_pause()
        rec["stop_total_s"], rec["state_after_stop"] = round(time.perf_counter() - t1, 2), "Paused"
        time.sleep(5)
        t2 = time.perf_counter()
        sbx = Sandbox.connect(sbx_id)
        rec["resume_total_s"], rec["state_after_resume"] = round(time.perf_counter() - t2, 2), "Running"
        rec["first_after_resume"] = ask_agent(endpoint, tok, agent_name, agent_ver, conv_id, sbx, COUNT_Q)
        rec["recover_total_s"] = round(rec["resume_total_s"] + rec["first_after_resume"]["guest_s"], 2)
        rec["warm_after_resume"] = ask_agent(endpoint, tok, agent_name, agent_ver, conv_id, sbx, COUNT_Q)
        lengths = [rec[k]["history_length"] for k in ("first", "warm", "first_after_resume", "warm_after_resume")]
        rec["state_kept"] = all(isinstance(x, int) for x in lengths) and all(b > a for a, b in zip(lengths, lengths[1:]))
        if not rec["state_kept"]:
            raise RuntimeError(f"conversation history did not keep growing across pause/resume: {lengths}")
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if sbx is not None:
            try:
                sbx.kill()
            except Exception as exc:  # noqa: BLE001
                rec["delete_error"] = f"{type(exc).__name__}: {exc}"
        rec["finished_at"] = now_iso()
    return rec


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    ag = sub.add_parser("agent", help="repeat the 3-run A-matched create/pause/resume protocol")
    ag.add_argument("--runs", type=int, default=3, help="number of runs (default: 3)")
    ag.add_argument("--template", default="base", help="E2B template name (default: base)")
    ag.add_argument("--out-dir", type=Path, default=ROOT / "evidence-local")

    pf = sub.add_parser("perf", help="repeat the D-matched cold/warm/concurrency/recovery protocol")
    pf.add_argument("--cold", type=int, default=5, help="number of cold sessions (default: 5)")
    pf.add_argument("--warm-turns", type=int, default=3, help="follow-up turns in warm session (default: 3)")
    pf.add_argument("--scale", default="4,8", help="comma-separated concurrency levels (default: 4,8)")
    pf.add_argument("--recovery", action="store_true", help="kill one sandbox and time replacement Ready")
    pf.add_argument("--template", default="base", help="E2B template name (default: base)")
    pf.add_argument("--out-dir", type=Path, default=ROOT / "evidence-local")
    args = ap.parse_args(argv)
    if getattr(args, "runs", 1) < 1 or getattr(args, "cold", 1) < 1 or getattr(args, "warm_turns", 1) < 1:
        ap.error("counts must be >= 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        endpoint = need_env("PROJECT_ENDPOINT")
        _ = need_env("E2B_API_URL")
        agent_name = os.environ.get("E2B_AGENT_NAME", "e2b-sandbox-benchmark-agent")
        agent_ver = os.environ.get("E2B_AGENT_VERSION", "1")
    except SettingMissing as exc:
        print(f"SETTING MISSING {exc}", file=sys.stderr)
        return 2
    try:
        tok = token()
        args.out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = args.out_dir / f"e2b-{args.mode}-{stamp}.json"
        if args.mode == "agent":
            runs = [agent_run(endpoint, tok, agent_name, agent_ver, args.template, i + 1) for i in range(args.runs)]
            doc = {"mode": "agent", "runs": runs}
            out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return 1 if any("error" in r or "delete_error" in r or not r.get("state_kept") for r in runs) else 0
        doc = {"mode": "perf", "endpoint": endpoint, "template": args.template}
        out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"E2B MEASURE FAIL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
