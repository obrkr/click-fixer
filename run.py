#!/usr/bin/env python3
"""Launch the ClickFix awareness simulator.

    python run.py                       # localhost only
    python run.py --host 0.0.0.0 --base-url http://training.corp.local:5000

The clipboard payload prints a Hello World banner and calls back to --base-url,
so every execution records itself against the right recipient.

Authorised internal security awareness training only.
"""

from __future__ import annotations

import argparse
import os
import sys

from clickfix_sim.app import create_app
from clickfix_sim.config import RUN_DIALOG_MAX, Config, run_dialog_fit


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost only)")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--base-url", default=None,
                   help="URL trainees reach the app on; the payload calls back to it")
    p.add_argument("--campaign", default=None, help="campaign name shown to trainees")
    p.add_argument("--contact", default=None, help="security contact address shown on debriefs")
    p.add_argument("--operator", default=None, help="team name shown to trainees")
    p.add_argument("--admin-token", default=None, help="fixed dashboard token instead of a random one")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    cfg = Config.from_env()
    if args.campaign:
        cfg.campaign_name = args.campaign
    if args.contact:
        cfg.security_contact = args.contact
    if args.operator:
        cfg.operator = args.operator
    if args.admin_token:
        cfg.admin_token = args.admin_token
    cfg.base_url = (args.base_url or f"http://{args.host}:{args.port}").rstrip("/")

    if "0.0.0.0" in cfg.base_url:
        p.error("the payload calls back to --base-url, so it must be an address the "
                "trainee's machine can actually reach (not 0.0.0.0)")

    app = create_app(cfg)

    print("=" * 72)
    # ASCII only: this banner goes to a Windows console, which is often still
    # on a legacy code page and turns anything else into mojibake.
    print("  ClickFix awareness simulator - TRAINING SIMULATION")
    print("=" * 72)
    print(f"  Campaign      : {cfg.campaign_name}")
    if not os.environ.get("CFSIM_SECRET_KEY"):
        print("  ! CFSIM_SECRET_KEY is unset, so callback signing keys rotate on restart.")
        print("    Set it if this campaign needs to survive a restart.")
    print(f"  Console       : {cfg.base_url}/")
    print(f"  Dashboard     : {cfg.base_url}/admin?token={cfg.admin_token}")
    print(f"  Results DB    : {cfg.db_path}")

    length, fits = run_dialog_fit(cfg)
    print(f"  Win payload   : {length}/{RUN_DIALOG_MAX} chars"
          f"{'  (fits the Run dialog)' if fits else '  *** TOO LONG ***'}")
    if not fits:
        print()
        print(f"  ! The Windows Run dialog accepts {RUN_DIALOG_MAX} characters and silently")
        print("    truncates the rest, so trainees would paste a broken command and the")
        print("    decoy tail would be lost. Shorten --base-url; a short hostname is the")
        print("    usual fix, and the URL is the most expensive part of the payload.")
    if args.host not in {"127.0.0.1", "localhost"}:
        print()
        print("  ! Bound to a non-local address. Only expose this on a network where")
        print("    you have written authorisation to run phishing simulations, and")
        print("    tell your service desk before you send the links.")
    print("=" * 72)

    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
