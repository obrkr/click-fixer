"""Campaign configuration.

Values come from environment variables (all prefixed ``CFSIM_``) so the tool can
be run straight from a shell or dropped into a container without editing code.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = PACKAGE_DIR.parent / "data" / "campaign.db"


@dataclass
class Config:
    # --- campaign identity -------------------------------------------------
    campaign_name: str = "ClickFix Awareness Campaign"
    # Shown on every debrief page so trainees know who to talk to. Set these.
    security_contact: str = "security@example.com"
    operator: str = "IT Security"

    # --- behaviour ---------------------------------------------------------
    # Where trainees reach this server. The payload calls back to it, so it has
    # to be an address their machine can actually resolve.
    base_url: str = "http://127.0.0.1:5000"
    # Milliseconds the fake verification spinner runs before "failing".
    spinner_ms: int = 1400

    # --- plumbing ----------------------------------------------------------
    db_path: Path = field(default_factory=lambda: DEFAULT_DB)
    admin_token: str = ""
    secret_key: str = ""

    def __post_init__(self) -> None:
        if not self.admin_token:
            self.admin_token = secrets.token_urlsafe(18)
        if not self.secret_key:
            self.secret_key = secrets.token_urlsafe(32)
        self.db_path = Path(self.db_path)
        self.base_url = self.base_url.rstrip("/")

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            campaign_name=os.environ.get("CFSIM_CAMPAIGN", cls.campaign_name),
            security_contact=os.environ.get("CFSIM_CONTACT", cls.security_contact),
            operator=os.environ.get("CFSIM_OPERATOR", cls.operator),
            base_url=os.environ.get("CFSIM_BASE_URL", cls.base_url),
            spinner_ms=int(os.environ.get("CFSIM_SPINNER_MS", cls.spinner_ms)),
            db_path=Path(os.environ.get("CFSIM_DB", str(DEFAULT_DB))),
            admin_token=os.environ.get("CFSIM_ADMIN_TOKEN", ""),
            secret_key=os.environ.get("CFSIM_SECRET_KEY", ""),
        )


# The Windows Run dialog's edit control accepts 259 characters and silently
# truncates a longer paste. Everything past that is lost, including the decoy
# tail — so an over-long payload does not just fail, it fails *and* throws away
# the part of the lesson we care about. This is why real ClickFix payloads are
# terse one-liners. The Windows payload below is built to fit inside it.
RUN_DIALOG_MAX = 259

# Length of the signature appended to the session id in the callback URL.
SIG_LEN = 6

# The tail comment is the real technique: the Run dialog scrolls to the end of a
# pasted string, so the victim only sees the reassuring "I am not a robot" part
# and never the command in front of it. Reproducing it is the whole lesson.
# Kept short deliberately — the authentic longer form ("reCAPTCHA Verification
# ID: 3819") costs ~22 more characters of a very tight budget.
DECOY_TAIL = "# ✅ ''I am not a robot - ID: 3819''"

# Windows gets one terse line because of RUN_DIALOG_MAX. `-NoExit` holds the
# console open, which costs 18 fewer characters than a Read-Host prompt and
# reads better anyway. The debrief page carries the detail.
_WIN_MSG = "TRAINING SIMULATION - Hello World. Never run a command a web page gave you."

_NIX_BANNER = (
    "clear; echo ''; "
    "echo '  ========================================================='; "
    "echo '   SECURITY AWARENESS TRAINING - THIS WAS A SIMULATION'; "
    "echo '  ========================================================='; "
    "echo ''; echo '  Hello World.'; echo ''; "
    "echo '  You just ran a command that a web page put in your'; "
    "echo '  clipboard. This one was harmless. A real one would have'; "
    "echo '  installed an infostealer before this line printed.'; echo ''; "
    "echo '  Rule: never paste and run a command you did not write.'; echo ''; "
)


def execution_token(cfg: Config, session_id: str) -> str:
    """Signed per-session token proving a callback came from our own payload.

    Without it /r/<code> would be an open endpoint anyone could curl to make the
    numbers say whatever they like. The signature is keyed on secret_key, which
    is regenerated on every start unless CFSIM_SECRET_KEY is set — so a campaign
    that outlives a restart must set it, or callbacks issued before the restart
    arrive unverified.
    """
    return hmac.new(
        cfg.secret_key.encode(), session_id.encode(), hashlib.sha256
    ).hexdigest()[:SIG_LEN]


def verify_execution_token(cfg: Config, session_id: str, token: str) -> bool:
    if not token:
        return False
    return hmac.compare_digest(execution_token(cfg, session_id), token)


def build_payload(cfg: Config, session_id: str, platform: str) -> str:
    """Return the harmless string the lure copies to the trainee's clipboard.

    ``platform`` is "windows" or "unix" (macOS and Linux share the shell form).
    It prints a banner and makes one HTTP GET to this campaign's own server so
    the execution records itself. Nothing here fetches or executes remote
    content, and the string is deliberately readable rather than obfuscated.
    """
    # Short path + short code: every character comes out of the 259 the Run
    # dialog allows, and the URL is the most expensive part of the payload.
    code = session_id + execution_token(cfg, session_id)
    beacon_url = f"{cfg.base_url}/r/{code}"

    # The callback goes after the banner is on screen: the console stays visible
    # while the trainee reads, so nothing is lost by waiting, and an unreachable
    # server never leaves them staring at a blank window.
    if platform == "windows":
        script = (
            f"Write-Host '{_WIN_MSG}' -F Yellow;"
            f"irm '{beacon_url}' -TimeoutSec 5 -EA 0|Out-Null;"
        )
        cmd = f'powershell -NoP -NoExit -C "{script}"'
    else:
        # Terminal has no such limit, so macOS/Linux keeps the fuller banner.
        cmd = (
            _NIX_BANNER
            + f"curl -fsS --max-time 5 '{beacon_url}' >/dev/null 2>&1 || true; "
            + "read -p '  Press Enter to close '"
        )

    return f"{cmd}    {DECOY_TAIL}"


def run_dialog_fit(cfg: Config) -> tuple[int, bool]:
    """Length of a representative Windows payload, and whether it fits.

    Checked before every campaign. A base_url longer than about 40 characters
    pushes the payload past the cap on its own, and the failure is silent — the
    trainee just gets a truncated command that errors.
    """
    sample = build_payload(cfg, "x" * 8, "windows")
    return len(sample), len(sample) <= RUN_DIALOG_MAX
