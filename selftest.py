#!/usr/bin/env python3
"""Self-test: exercises every route, the funnel maths, and the payload itself.

    python selftest.py

Run this after changing anything, and before any live campaign — the payload
execution check is the one that proves the clipboard string is still harmless.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

from clickfix_sim.app import create_app
from clickfix_sim.config import (
    RUN_DIALOG_MAX,
    Config,
    build_payload,
    execution_token,
    run_dialog_fit,
    verify_execution_token,
)
from clickfix_sim.scenarios import SCENARIOS

WIN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126"
MAC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605"

failures: list[str] = []


def check(label: str, resp, *needles: str, code: int = 200) -> None:
    try:
        assert resp.status_code == code, f"status {resp.status_code} != {code}"
        body = resp.get_data(as_text=True)
        for n in needles:
            assert n in body, f"missing {n!r}"
    except AssertionError as e:
        failures.append(f"{label}: {e}")
        print(f"  FAIL  {label}: {e}")
    else:
        print(f"  ok    {label}")


def main() -> int:
    db = pathlib.Path(tempfile.mkdtemp()) / "selftest.db"
    cfg = Config(db_path=db, admin_token="selftest-token")
    app = create_app(cfg)
    c = app.test_client()
    win = {"User-Agent": WIN_UA}

    print("routes")
    check("console", c.get("/", headers=win), "Operator console", "Scenarios")
    check("health", c.get("/health"), '"ok"')
    check("robots", c.get("/robots.txt"), "Disallow")
    for sid in SCENARIOS:
        check(f"lure /s/{sid}", c.get(f"/s/{sid}?t=alice", headers=win),
              "cfOverlay", "Win + R", "powershell", "TRAINING SIMULATION")
    check("mac instructions", c.get("/s/human_check", headers={"User-Agent": MAC_UA}),
          "⌘ Space", "Hello World.")
    check("unknown scenario 404", c.get("/s/nope", headers=win), code=404)

    print("telemetry")
    for stage in ("verify_click", "clipboard_copy", "focus_lost", "ran_command"):
        r = c.post("/api/event", json={"stage": stage, "scenario": "human_check",
                                       "platform": "windows"})
        check(f"stage {stage}", r, '"ok":true')
    check("bad stage rejected", c.post("/api/event", json={"stage": "rm -rf"}), code=400)

    print("outcomes")
    check("debrief", c.get("/caught?s=human_check", headers=win),
          "simulated attack", "decoy tail", "Hello World")
    check("reported", c.get("/reported?s=human_check", headers=win), "Good catch")

    print("admin")
    check("token required", c.get("/admin"), code=403)
    check("dashboard", c.get("/admin?token=selftest-token"), "Funnel", "Ran the command")
    check("csv export", c.get("/admin/export.csv?token=selftest-token"), "session_id,recipient")

    print("funnel maths")
    summary = app.config["CFSIM_STORE"].summary()
    counts = {f["stage"]: f["count"] for f in summary["funnel"]}
    ordered = list(counts.values())
    if ordered != sorted(ordered, reverse=True):
        failures.append(f"funnel not monotonic: {counts}")
        print(f"  FAIL  funnel not monotonic: {counts}")
    else:
        print(f"  ok    funnel monotonic {counts}")
    if summary["reported"] < 1:
        failures.append("reported event not counted")
        print("  FAIL  reported event not counted")
    else:
        print("  ok    report counted")

    print("payload safety")
    # The invariant is not "makes no network call" — beacon mode deliberately
    # calls home to prove execution. It is "never fetches and executes remote
    # content, and never talks to a host other than this campaign's own".
    banned = ("iex", "invoke-expression", "downloadstring", "downloadfile",
              "frombase64string", "-enc ", "-encodedcommand", "certutil",
              "bitsadmin", "mshta", "regsvr32", "rundll32", "schtasks",
              "reg add", "new-service", "-w hidden", "-windowstyle hidden")
    base = "http://127.0.0.1:5000"
    c2 = Config(admin_token="x", base_url=base)
    for plat in ("windows", "unix"):
        p = build_payload(c2, "sid12345", plat)
        low = p.lower()
        hits = [b for b in banned if b in low]
        urls = re.findall(r"https?://[^\s'\"]+", p)
        stray = [u for u in urls if not u.startswith(base)]
        piped = re.search(r"(curl|wget|invoke-restmethod|iwr|irm)[^;|]*\|\s*(sh|bash|zsh|iex)", low)
        label = f"payload[{plat}]"
        if hits:
            failures.append(f"{label} contains {hits}")
            print(f"  FAIL  {label} contains {hits}")
        elif stray:
            failures.append(f"{label} calls a host outside base_url: {stray}")
            print(f"  FAIL  {label} calls outside base_url: {stray}")
        elif piped:
            failures.append(f"{label} pipes a download into an interpreter")
            print(f"  FAIL  {label} pipes a download into an interpreter")
        elif not urls:
            failures.append(f"{label} has no callback — execution could not be verified")
            print(f"  FAIL  {label} has no callback URL")
        else:
            print(f"  ok    {label} safe ({len(urls)} url(s), all campaign-scoped)")

    print("run dialog length cap")
    # The bug this catches is silent and total: Windows truncates a longer paste
    # without telling anyone, so the command breaks *and* the decoy tail is lost.
    for base in ("http://127.0.0.1:5000", "http://training.corp.local:5000"):
        c3 = Config(admin_token="x", base_url=base)
        n, fits = run_dialog_fit(c3)
        host = base.split("//")[1]
        if fits:
            print(f"  ok    {host}: {n}/{RUN_DIALOG_MAX}")
        else:
            failures.append(f"{host}: {n} > {RUN_DIALOG_MAX}")
            print(f"  FAIL  {host}: {n} > {RUN_DIALOG_MAX} (would be truncated)")
        # The decoy tail must survive, or the lesson goes with it.
        p = build_payload(c3, "x" * 8, "windows")
        if p[:RUN_DIALOG_MAX].rstrip().endswith("''"):
            print(f"  ok    decoy tail survives truncation @ {base.split('//')[1]}")
        else:
            failures.append(f"decoy tail lost @ {base}")
            print(f"  FAIL  decoy tail lost @ {base}")

    print("execution confirmation")
    tok = execution_token(cfg, "sess-a")
    checks = [
        ("valid token accepted", verify_execution_token(cfg, "sess-a", tok), True),
        ("wrong session rejected", verify_execution_token(cfg, "sess-b", tok), False),
        ("empty token rejected", verify_execution_token(cfg, "sess-a", ""), False),
        ("garbage token rejected", verify_execution_token(cfg, "sess-a", "deadbeef"), False),
    ]
    for label, got, want in checks:
        if got is want:
            print(f"  ok    {label}")
        else:
            failures.append(f"{label}: got {got}")
            print(f"  FAIL  {label}: got {got}")

    check("signed callback accepted", c.get(f"/r/sess-a{tok}"), '"ok":true')
    check("unsigned callback still recorded", c.get("/r/sess-cbadbad"), '"ok":true')
    check("malformed code rejected", c.get("/r/short"), code=400)

    graded = {s["session_id"]: s["evidence"] for s in app.config["CFSIM_STORE"].sessions()}
    if graded.get("sess-a") == "confirmed":
        print("  ok    signed callback graded 'confirmed'")
    else:
        failures.append(f"sess-a graded {graded.get('sess-a')!r}, expected 'confirmed'")
        print(f"  FAIL  sess-a graded {graded.get('sess-a')!r}")
    if graded.get("sess-c") == "unverified_callback":
        print("  ok    unsigned callback graded 'unverified_callback'")
    else:
        failures.append(f"sess-c graded {graded.get('sess-c')!r}")
        print(f"  FAIL  sess-c graded {graded.get('sess-c')!r}")

    if sys.platform == "win32":
        # The real payload, against a base_url with nothing listening: the
        # callback must fail silently rather than break the trainee's banner.
        p = build_payload(Config(admin_token="x", base_url="http://127.0.0.1:9"),
                          "sid12345", "windows")
        r = subprocess.run(p, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=60)
        if "Hello World." in r.stdout:
            print("  ok    payload executes and prints the training banner")
        else:
            failures.append(f"payload did not print banner (exit {r.returncode})")
            print(f"  FAIL  payload did not print banner (exit {r.returncode})")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
