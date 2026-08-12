"""SQLite-backed event store for campaign telemetry.

Deliberately minimal: it records which stage of the lure each session reached
and nothing else. There is no credential capture, no keystroke logging and no
collection of anything the operator did not put in the recipient token.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Ordered funnel. Index = how far down the attack chain the trainee travelled.
STAGE_ORDER: list[str] = [
    "lure_view",          # opened the lure page
    "verify_click",       # clicked the fake "verify" / "fix it" control
    "clipboard_copy",     # payload landed in their clipboard
    "focus_lost",         # left the browser — Run dialog / Terminal likely open
    "ran_command",        # confirmed execution (self-reported or console callback)
    "caught_view",        # reached the debrief
    "debrief_complete",   # finished the knowledge check
]

STAGE_LABELS = {
    "lure_view": "Opened lure",
    "verify_click": "Clicked verify",
    "clipboard_copy": "Copied payload",
    "focus_lost": "Left browser",
    "ran_command": "Ran command",
    "caught_view": "Saw debrief",
    "debrief_complete": "Completed debrief",
}

# Logged but outside the funnel: this is the *win* condition.
REPORTED = "reported"
# Also outside the funnel: fires when focus comes back, carrying how long they
# were away. Duration is what separates "opened the Run dialog" from "checked
# Slack for a minute".
FOCUS_RETURNED = "focus_returned"
VALID_STAGES = set(STAGE_ORDER) | {REPORTED, FOCUS_RETURNED}

# How strong the evidence is that the command actually ran.
EVIDENCE = {
    "confirmed": "Confirmed — the command called home",
    "unverified_callback": "Callback received but signature did not verify",
    "self_reported": "Self-reported — they clicked 'I have completed the steps'",
    "inferred": "Inferred — left the browser after copying",
    "none": "No execution evidence",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    session_id  TEXT    NOT NULL,
    recipient   TEXT,
    scenario    TEXT,
    stage       TEXT    NOT NULL,
    platform    TEXT,
    meta        TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_stage   ON events(stage);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EventStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # -- writes -------------------------------------------------------------

    def record(
        self,
        session_id: str,
        stage: str,
        *,
        scenario: str | None = None,
        recipient: str | None = None,
        platform: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        if stage not in VALID_STAGES:
            raise ValueError(f"unknown stage {stage!r}")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events (ts, session_id, recipient, scenario, stage, platform, meta)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _utcnow(),
                    session_id,
                    recipient,
                    scenario,
                    stage,
                    platform,
                    json.dumps(meta or {}, ensure_ascii=False),
                ),
            )

    def reset(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM events")

    # -- reads --------------------------------------------------------------

    def all_events(self) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM events ORDER BY id").fetchall()

    def sessions(self) -> list[dict[str, Any]]:
        """Collapse the event log into one row per trainee session."""
        rows = self.all_events()
        sessions: dict[str, dict[str, Any]] = {}

        for row in rows:
            sid = row["session_id"]
            s = sessions.setdefault(
                sid,
                {
                    "session_id": sid,
                    "recipient": None,
                    "scenario": None,
                    "platform": None,
                    "first_seen": row["ts"],
                    "last_seen": row["ts"],
                    "stages": set(),
                    "reported": False,
                    "reported_at": None,
                    "copied_at": None,
                    "confirmed": False,
                    "callback_seen": False,
                    "self_reported": False,
                    "away_ms": None,
                },
            )
            s["last_seen"] = row["ts"]
            s["recipient"] = row["recipient"] or s["recipient"]
            s["scenario"] = row["scenario"] or s["scenario"]
            s["platform"] = row["platform"] or s["platform"]

            try:
                meta = json.loads(row["meta"] or "{}")
            except (ValueError, TypeError):
                meta = {}

            if row["stage"] == REPORTED:
                s["reported"] = True
                s["reported_at"] = s["reported_at"] or row["ts"]
            elif row["stage"] == FOCUS_RETURNED:
                away = meta.get("away_ms")
                if isinstance(away, (int, float)):
                    s["away_ms"] = max(s["away_ms"] or 0, int(away))
            else:
                s["stages"].add(row["stage"])
                if row["stage"] == "clipboard_copy" and not s["copied_at"]:
                    s["copied_at"] = row["ts"]
                if row["stage"] == "ran_command":
                    if meta.get("via") == "beacon":
                        s["callback_seen"] = True
                        s["confirmed"] = s["confirmed"] or bool(meta.get("verified"))
                    else:
                        s["self_reported"] = True

        out = []
        for s in sessions.values():
            reached = [st for st in STAGE_ORDER if st in s["stages"]]
            s["furthest"] = reached[-1] if reached else "lure_view"
            s["depth"] = STAGE_ORDER.index(s["furthest"])
            s["compromised"] = s["depth"] >= STAGE_ORDER.index("ran_command")
            s["seconds_to_copy"] = _delta(s["first_seen"], s["copied_at"])
            s["evidence"] = _grade_evidence(s)
            s["evidence_label"] = EVIDENCE[s["evidence"]]
            del s["stages"]
            out.append(s)

        out.sort(key=lambda r: r["first_seen"], reverse=True)
        return out

    def summary(self) -> dict[str, Any]:
        sessions = self.sessions()
        total = len(sessions)
        funnel = []
        for stage in STAGE_ORDER:
            rank = STAGE_ORDER.index(stage)
            count = sum(1 for s in sessions if s["depth"] >= rank)
            funnel.append(
                {
                    "stage": stage,
                    "label": STAGE_LABELS[stage],
                    "count": count,
                    "pct": round(100 * count / total, 1) if total else 0.0,
                }
            )

        reported = sum(1 for s in sessions if s["reported"])
        compromised = sum(1 for s in sessions if s["compromised"])
        confirmed = sum(1 for s in sessions if s["evidence"] == "confirmed")
        times = [s["seconds_to_copy"] for s in sessions if s["seconds_to_copy"] is not None]
        evidence_mix = {key: 0 for key in EVIDENCE}
        for s in sessions:
            evidence_mix[s["evidence"]] += 1

        return {
            "total_sessions": total,
            "funnel": funnel,
            "reported": reported,
            "report_rate": round(100 * reported / total, 1) if total else 0.0,
            "compromised": compromised,
            "compromise_rate": round(100 * compromised / total, 1) if total else 0.0,
            "confirmed": confirmed,
            "confirmed_rate": round(100 * confirmed / total, 1) if total else 0.0,
            "evidence_mix": [
                {"key": k, "label": EVIDENCE[k], "count": v}
                for k, v in evidence_mix.items() if v
            ],
            "median_seconds_to_copy": _median(times),
            "by_scenario": _group_by_scenario(sessions),
        }


def _grade_evidence(session: dict[str, Any]) -> str:
    """Strongest available evidence that this session ran the command."""
    if session["confirmed"]:
        return "confirmed"
    if session["callback_seen"]:
        return "unverified_callback"
    if session["self_reported"]:
        return "self_reported"
    # Focus left the browser after the payload was copied. On its own that is
    # circumstantial — but a short absence right after the copy matches opening
    # the Run dialog far better than it matches wandering off.
    if session["depth"] >= STAGE_ORDER.index("focus_lost"):
        return "inferred"
    return "none"


def _delta(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        return int(
            (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
        )
    except ValueError:
        return None


def _median(values: Iterable[int]) -> int | None:
    vals = sorted(values)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) // 2


def _group_by_scenario(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for s in sessions:
        key = s["scenario"] or "unknown"
        b = buckets.setdefault(key, {"scenario": key, "sessions": 0, "compromised": 0, "reported": 0})
        b["sessions"] += 1
        b["compromised"] += int(s["compromised"])
        b["reported"] += int(s["reported"])
    for b in buckets.values():
        b["compromise_rate"] = round(100 * b["compromised"] / b["sessions"], 1)
        b["report_rate"] = round(100 * b["reported"] / b["sessions"], 1)
    return sorted(buckets.values(), key=lambda b: -b["sessions"])
