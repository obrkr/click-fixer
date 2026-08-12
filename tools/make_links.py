#!/usr/bin/env python3
"""Generate per-recipient lure links for a campaign.

    python tools/make_links.py --base-url http://training.corp.local:5000 people.txt
    python tools/make_links.py --base-url http://tr.corp:5000 --spread people.txt --out links.csv

`people.txt` is one recipient per line (blank lines and `#` comments ignored).
A CSV is also accepted — the first column is used, and a header row containing
"email" or "recipient" is skipped.

The recipient tag is what ties a confirmed execution back to a person in the
dashboard, so results arrive already attributed and nobody has to be chased
individually. Tag with whatever your organisation actually uses — an email, a
staff number, or an opaque id if you would rather the results not be personally
identifiable at all.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clickfix_sim.scenarios import SCENARIOS  # noqa: E402


def read_recipients(path: Path) -> list[str]:
    out: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            value = row[0].strip()
            if not value or value.startswith("#"):
                continue
            if not out and value.lower() in {"email", "recipient", "user", "address"}:
                continue  # header
            out.append(value)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("recipients", type=Path, help="file of recipients, one per line")
    p.add_argument("--base-url", required=True, help="URL trainees reach the simulator on")
    p.add_argument("--scenario", default="human_check", choices=sorted(SCENARIOS),
                   help="scenario to send (default: human_check)")
    p.add_argument("--spread", action="store_true",
                   help="rotate through all scenarios instead of sending one")
    p.add_argument("--out", type=Path, help="write CSV here instead of stdout")
    args = p.parse_args()

    if not args.recipients.exists():
        p.error(f"no such file: {args.recipients}")

    people = read_recipients(args.recipients)
    if not people:
        p.error(f"{args.recipients} contained no recipients")

    base = args.base_url.rstrip("/")
    scenarios = sorted(SCENARIOS) if args.spread else [args.scenario]

    rows = []
    for i, person in enumerate(people):
        scenario = scenarios[i % len(scenarios)]
        rows.append([person, scenario, f"{base}/s/{scenario}?t={quote(person, safe='')}"])

    handle = args.out.open("w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        writer = csv.writer(handle)
        writer.writerow(["recipient", "scenario", "link"])
        writer.writerows(rows)
    finally:
        if args.out:
            handle.close()

    if args.out:
        print(f"{len(rows)} links -> {args.out}", file=sys.stderr)
    # Sent as mail-merge fodder; the simulator does not send anything itself,
    # which keeps delivery, suppression lists and consent in your own tooling.
    print(f"{len(rows)} recipients across {len(scenarios)} scenario(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
