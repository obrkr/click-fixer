"""Lure scenarios.

Each scenario is a different pretext wrapped around the same core ClickFix
mechanic: convince the user to copy something, open a system run box, paste and
press Enter. Styling is deliberately *generic* — familiar layouts and wording,
but no third-party logos, wordmarks or domains. Cloning a real vendor's brand
turns a training asset into something you cannot defend if it leaks.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    summary: str
    lure_template: str
    widget: str            # "checkbox" | "button"
    trigger_label: str
    headline: str
    subhead: str
    failure_title: str
    failure_body: str
    real_world: str
    red_flags: list[str] = field(default_factory=list)


SCENARIOS: dict[str, Scenario] = {
    "human_check": Scenario(
        id="human_check",
        name="\"Verify you are human\" checkbox",
        summary=(
            "The classic. A generic bot-check interstitial in front of content the "
            "user actually wants. The check 'fails' and offers a manual workaround."
        ),
        lure_template="lures/human_check.html",
        widget="checkbox",
        trigger_label="I'm not a robot",
        headline="Verify you are human",
        subhead="This site needs to review the security of your connection before proceeding.",
        failure_title="Automatic verification failed",
        failure_body=(
            "Your browser could not complete the check automatically. "
            "Finish verification manually using the steps below."
        ),
        real_world=(
            "Used at scale since 2024 to deliver infostealers such as Lumma and "
            "Vidar, and remote access tools, from compromised WordPress sites and "
            "malvertising redirects."
        ),
        red_flags=[
            "A real bot check never asks you to leave the browser.",
            "No legitimate CAPTCHA involves the Windows Run dialog or a terminal.",
            "The 'verification' steps are keyboard shortcuts, not a puzzle.",
        ],
    ),
    "doc_render": Scenario(
        id="doc_render",
        name="Shared document won't display",
        summary=(
            "A shared file preview that 'fails to render' and offers a one-click "
            "fix. Very effective in email-led campaigns because the user arrives "
            "already expecting a document."
        ),
        lure_template="lures/doc_render.html",
        widget="button",
        trigger_label="Fix display error",
        headline="This document could not be displayed",
        subhead="A rendering component on this device is out of date.",
        failure_title="Automatic repair unavailable",
        failure_body=(
            "This document is protected and cannot be repaired automatically. "
            "Apply the fix manually to view the file."
        ),
        real_world=(
            "Pairs with 'someone shared a file with you' phishing mail. The "
            "pretext explains the friction, so users push through it."
        ),
        red_flags=[
            "A document viewer never needs you to run a command to render a page.",
            "The 'fix' is identical regardless of which document you opened.",
            "Genuine repair tools are installed software, not copy-paste snippets.",
        ],
    ),
    "meeting_audio": Scenario(
        id="meeting_audio",
        name="Meeting mic/camera driver error",
        summary=(
            "A video call join page that reports a device driver problem. Urgency "
            "does the work — the user believes colleagues are waiting for them."
        ),
        lure_template="lures/meeting_audio.html",
        widget="button",
        trigger_label="Run audio fix",
        headline="We can't reach your microphone",
        subhead="Your audio driver did not respond when joining this meeting.",
        failure_title="Driver repair needs one manual step",
        failure_body=(
            "Browser sandboxing prevents us from resetting the device. "
            "Run the reset yourself using the steps below, then rejoin."
        ),
        real_world=(
            "Fake meeting invites are a favourite against finance staff and "
            "executive assistants; time pressure suppresses the instinct to check."
        ),
        red_flags=[
            "Time pressure is the payload — it stops you checking.",
            "Meeting software fixes devices in its own settings, not via Win+R.",
            "You did not schedule this meeting from this link.",
        ],
    ),
    "browser_update": Scenario(
        id="browser_update",
        name="Critical browser update",
        summary=(
            "A full-page update notice claiming the browser is unsafe and must be "
            "patched manually. Leans on the security reflex itself."
        ),
        lure_template="lures/browser_update.html",
        widget="button",
        trigger_label="Apply security patch",
        headline="Your browser is missing a critical security update",
        subhead="Version out of date — this device is exposed to known exploits.",
        failure_title="Automatic update blocked by policy",
        failure_body=(
            "Device policy prevented the updater from running. "
            "Apply the patch manually using the steps below."
        ),
        real_world=(
            "Descended from the older 'fake update' campaigns; ClickFix removed "
            "the download step, so nothing hits the browser's download warnings."
        ),
        red_flags=[
            "Browsers update themselves; they never hand you a command.",
            "A web page cannot know your patch level with any authority.",
            "Real policy blocks send you to IT, not to a run box.",
        ],
    ),
}


# The instruction sets the lure displays. These are the actual ClickFix steps,
# reproduced so trainees recognise the exact sequence in the wild.
STEPS = {
    "windows": [
        {"key": "⊞ Win + R", "text": "Open the Windows Run dialog"},
        {"key": "Ctrl + V", "text": "Paste the verification token"},
        {"key": "Enter", "text": "Press Enter to complete verification"},
    ],
    "unix": [
        {"key": "⌘ Space", "text": "Open Spotlight, type Terminal, press Enter"},
        {"key": "⌘ V", "text": "Paste the verification token"},
        {"key": "Return", "text": "Press Return to complete verification"},
    ],
}


def get_scenario(scenario_id: str) -> Scenario | None:
    return SCENARIOS.get(scenario_id)
