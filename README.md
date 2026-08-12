# Click Fixer

![Vibe Coded](https://img.shields.io/badge/vibe-coded-ff5fa8?style=for-the-badge)
![Built with Claude Code](https://img.shields.io/badge/built%20with-Claude%20Code-8a5cf6?style=for-the-badge)
![Authorised Use Only](https://img.shields.io/badge/authorised%20use-only-d93025?style=for-the-badge)
![Benign Payload](https://img.shields.io/badge/payload-benign-2ea44f?style=for-the-badge)
![Self Verifying](https://img.shields.io/badge/execution-self%20verifying-3b82f6?style=for-the-badge)

A self-hosted **ClickFix / fake-CAPTCHA** simulator for security awareness training. It reproduces the lure faithfully — the fake check, the fake failure, the clipboard hijack, the "just press Win+R and paste" instructions — and then replaces the malware with a Hello World banner and a debrief page. The payload calls home, so every execution records itself against the right person. No endpoint investigation, no self-reported numbers.

> **This project is fully vibe coded.** The lures, the funnel maths, the payload construction and the self-test were all built through conversational, AI-assisted development rather than a planned build. It has been verified with real automated runs — the payload is actually executed through `CreateProcess` the way the Run dialog invokes it, and a four-recipient campaign is simulated end to end — but read the code yourself before pointing it at real colleagues. Tooling that emails your staff a convincing phishing page deserves that much.

> **Built with Python 3, Flask and SQLite.** Flask is the only dependency — SQLite comes from the standard library, the pages are Jinja2 templates, and the lure controller is one vanilla JavaScript file. Callback signing uses stdlib `hmac`/`hashlib`. No build step, no bundler, no frontend framework and no CDN: a training page that fails to load is a wasted send.

---

## Contents

- [What ClickFix is](#what-clickfix-is)
- [Features](#features)
- [Quick start](#quick-start)
- [Running a campaign](#running-a-campaign)
- [Scenarios](#scenarios)
- [The payload](#the-payload)
- [The 259-character trap](#the-259-character-trap)
- [How execution is validated](#how-execution-is-validated)
- [What gets measured](#what-gets-measured)
- [What gets recorded](#what-gets-recorded)
- [Before you run a campaign](#before-you-run-a-campaign)
- [After the campaign](#after-the-campaign)
- [Project structure](#project-structure)
- [How it's built](#how-its-built)

---

## What ClickFix is

A web page claims something failed — a bot check, a document, a microphone, a browser update — and offers a "manual fix":

> 1. Press **Win + R**
> 2. Press **Ctrl + V**
> 3. Press **Enter**

The page has already written a command into the clipboard. The user pastes and runs it themselves.

It works because a web page cannot execute code on your machine, so it convinces you to do it for it. Nothing is downloaded, so nothing is scanned or blocked, and every "are you sure?" control is satisfied because you gave the permission.

The finishing touch is the decoy tail. The payload ends with a long comment such as `# ✅ ''I am not a robot - ID: 3819''`, and the Run dialog scrolls to the *end* of pasted text — so that reassuring string is the last thing the user sees before pressing Enter. The real command is off-screen to the left.

This simulator reproduces all of it, decoy tail included, because the tail is the part people need to have seen once.

---

## Features

- **Four lure scenarios**, each a different pretext around the same mechanic.
- **Self-verifying payload.** The command calls back with a signed per-session token, so "they ran it" is evidence, not a self-report.
- **Automatic attribution.** Tag a link per recipient and confirmed executions arrive already matched to a person.
- **OS-aware instructions.** Win+R on Windows, Terminal on macOS and Linux, chosen from the user agent.
- **Full funnel**, from page view to clipboard copy to leaving the browser to execution — plus **report rate**, the number actually worth optimising.
- **Teaching-moment debrief** that dissects the exact command they were given, in colour, and explains the decoy-tail trick.
- **A separate debrief for people who report it**, because rewarding the correct behaviour is the point.
- **A self-test that enforces payload safety as an invariant** — a careless edit fails the test rather than the campaign.

---

## Quick start

```bash
pip install -r requirements.txt
python run.py
```

Open the operator console at <http://127.0.0.1:5000/>. It lists the scenarios, the dashboard link and the generated admin token, and binds to localhost only unless you pass `--host`.

Verify everything, including that the clipboard payload is still harmless:

```bash
python selftest.py
```

The payload calls back to `--base-url`, so that has to be an address trainees can actually reach. The launcher refuses to start with `0.0.0.0` rather than fail silently later.

```bash
python run.py --host 0.0.0.0 --base-url http://tr.corp.local:5000 --campaign "Q3 ClickFix" --contact soc@yourcorp.com --operator "Information Security"
```

Put it behind a reverse proxy with TLS. The bundled server is Flask's development server and is not meant to face a real user population unproxied.

**Set `CFSIM_SECRET_KEY`** for anything that has to survive a restart — without it the callback signing key rotates and earlier callbacks arrive unverified.

---

## Running a campaign

Generate tagged links for a staff list:

```bash
python tools/make_links.py --base-url http://tr.corp.local:5000 --spread people.txt --out links.csv
```

`--spread` rotates recipients across all four scenarios, giving you a per-scenario comparison from a single send. `people.txt` is one recipient per line; a CSV works too.

Mail-merge `links.csv`, then read the dashboard. The simulator never sends mail itself, so delivery, suppression lists and consent stay in your own tooling.

What you get back, with nothing to chase up:

```
recipient             scenario        furthest      evidence      reported
alice@corp.example    browser_update  Ran command   confirmed     0
bob@corp.example      doc_render      Opened lure   none          1
carol@corp.example    human_check     Ran command   confirmed     0
dan@corp.example      meeting_audio   Opened lure   none          0
```

---

## Scenarios

Send trainees `/s/<id>`; add `?t=alice@example.com` to tag them in the results.

| id | Pretext |
|---|---|
| `human_check` | "Verify you are human" checkbox that fails and offers manual steps |
| `doc_render` | Shared PDF that "cannot be displayed" and offers a fix |
| `meeting_audio` | Video call reporting a microphone driver failure |
| `browser_update` | Full-page "critical security update" notice |

Styling is deliberately generic — familiar layouts and wording, **no third-party logos, wordmarks or lookalike domains**. Cloning a real vendor's brand turns a training asset into something you cannot defend if it leaks, and into a trademark problem. Resist the urge to add the logos back.

---

## The payload

One payload, and it does two things: prints a Hello World training banner, and makes a single HTTP GET back to your own server so the execution records itself.

On Windows it is a `powershell -NoP -NoExit -C` one-liner. macOS and Linux get the shell equivalent with a fuller banner. There is no download, no encoding, no obfuscation, no persistence, and nothing touching the registry, scheduled tasks or startup.

`selftest.py` enforces that as an invariant. The payload may not contain fetch-and-execute primitives (`iex`, `DownloadString`, `FromBase64String`, `certutil`, `mshta`, …), may not pipe a download into an interpreter, and **every URL in it must be inside your configured `--base-url`**.

---

## The 259-character trap

**The Windows Run dialog accepts 259 characters and silently truncates anything longer.** A payload over the limit does not merely fail — it fails *and* throws away the decoy tail at the end, which is the part of the lesson you built the exercise around. This is why real ClickFix payloads are terse one-liners.

The Windows payload here is built to fit — 241 characters against a localhost URL. The budget is tight enough that a long `--base-url` breaks it on its own, so the length is checked and reported at startup and on the operator console, and `selftest.py` fails if it exceeds the cap:

```
  Win payload   : 241/259 chars  (fits the Run dialog)
```

If you see the warning, shorten the hostname. The URL is the most expensive part of the payload.

macOS and Linux paste into Terminal, which has no such limit.

---

## How execution is validated

**The payload verifies itself.** You never touch an individual machine.

The command makes a single HTTP GET to `/r/<code>`, where `code` is the session id plus an HMAC over it keyed on `secret_key`. Only something executing on the trainee's machine can reach that endpoint, and the signature stops anyone from curling it to make the numbers say whatever they like. The session flips to **Confirmed** in the dashboard, already attributed to whoever the link was tagged for.

### When the callback does not arrive

A web page cannot see the Run dialog, so without the callback you are left with inference. Two weaker grades exist:

| Grade | Meaning |
|---|---|
| **Inferred** | Focus left the browser after the copy, with the duration recorded. Win+R → Ctrl+V → Enter is a few seconds; a twenty-minute gap is someone who wandered off. Circumstantial — do not report it as a compromise rate. |
| **Self-reported** | They clicked "I have completed the steps". A button, not evidence. |
| **Callback (unsigned)** | Recorded, because losing real execution data is worse, but never counted as confirmed. Almost always a restart rotated the signing key. |

### What nothing can tell you

**Paste without Enter is unobservable.** A trainee who pastes into the Run dialog, hesitates, and closes it sends no callback and looks identical to someone who alt-tabbed away. That user got the whole way to the edge and you will never know. Quote the confirmed number as a floor, not a total.

At population scale the campaign's own telemetry is a supplement, not the source of truth. The durable detection is process ancestry — `explorer.exe` spawning `powershell.exe`, `cmd.exe` or `mshta.exe` — which catches ClickFix whatever the lure looked like, and works for attacks that never touched your simulation.

---

## What gets measured

The dashboard (`/admin`) shows a funnel:

| Stage | Meaning |
|---|---|
| Opened lure | Landed on the page |
| Clicked verify | Engaged with the fake check |
| Copied payload | Command reached their clipboard |
| Left browser | Focus moved away after the copy |
| **Ran command** | Confirmed by callback |
| Saw debrief / Completed debrief | Reached and finished the teaching page |

Plus **report rate** — trainees who clicked "This page looks wrong" instead of following the steps. Real attacks have no such link; it costs a little realism to carry the metric that predicts how fast you find out about a real one.

CSV export and a reset button are on the dashboard.

---

## What gets recorded

A random session id in a cookie, whatever recipient tag you put in the link, which stage each session reached, timings, and the user-agent string.

**Not** recorded: passwords, keystrokes, form data, clipboard reads. There is no code in this project that collects any of them, and there is no form for a trainee to type into.

---

## Before you run a campaign

Phishing simulation is a legitimate exercise that becomes a problem when it is run without cover.

- Get **written authorisation** from whoever owns the risk, covering scope and dates.
- **Tell your service desk.** ClickFix simulations generate real security reports — that is the desired outcome, and they need to know not to open an incident for each one.
- Check your obligations for staff monitoring in your jurisdiction. Works councils and employee representatives often need notice.
- Only target people your organisation is authorised to test. Never customers, never the general public, never anyone outside the agreed scope.
- **Report in aggregate.** Naming individuals who fell for a well-built lure suppresses reporting, and reporting is the control you are actually trying to build.

---

## After the campaign

The debrief pages do the teaching, but the exercise only pays off if you follow up:

- Share aggregate results with a short "here is what to look for" note.
- Reinforce the single rule: **never paste a command into Run, PowerShell or Terminal because a web page told you to.** There is no legitimate version of that request.
- Make reporting frictionless and thank people publicly for doing it.
- Pair it with detection work: process telemetry for `explorer.exe` spawning `powershell.exe`, and the `RunMRU` registry key, both show this pattern clearly.

---

## Project structure

```
run.py                      launcher and CLI
selftest.py                 route, funnel, length-cap and payload-safety checks
tools/make_links.py         per-recipient lure links for a mail merge
clickfix_sim/
  app.py                    Flask routes
  config.py                 campaign config, payload construction, token signing
  scenarios.py              the four lure pretexts and their step lists
  store.py                  SQLite event log, funnel maths, evidence grading
  templates/
    lures/                  the four lure pages
    partials/verify.html    the shared ClickFix widget
    caught.html             debrief for trainees who followed through
    reported.html           debrief for trainees who reported it
    console.html            operator console
    dashboard.html          results
  static/                   css + the lure controller script
data/campaign.db            results (created on first run)
```

---

## How it's built

Python 3 and Flask, with SQLite through the standard library. Flask is the only dependency. No build step, no bundler, no JavaScript framework — the lure controller is a single vanilla script, because a training page that fails to load is a wasted send.

The interesting parts:

- **`config.py`** builds the payload and signs the callback token. Everything about the Run dialog's character budget lives here.
- **`store.py`** collapses the raw event log into one row per session and grades how strong the execution evidence is.
- **`static/js/clickfix.js`** drives the lure: clipboard write inside the user gesture, graceful fallback when the clipboard is blocked, and the focus-loss timing signal. The spinner transition is armed *before* the clipboard call so a clipboard failure can never strand someone on a permanent "Checking your device…".
- **`selftest.py`** is the safety net, and the only file worth reading first if you plan to change the payload.
