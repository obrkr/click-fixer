/* ClickFix lure controller — SECURITY AWARENESS TRAINING SIMULATION.
 *
 * Reproduces the interaction pattern of a real ClickFix page so trainees learn
 * to recognise it: fake check -> fake failure -> "helpful" manual steps, with
 * the payload silently placed in the clipboard at the moment of the click.
 *
 * The payload itself is a harmless banner (see config.py). This script does not
 * execute anything, download anything, or read anything back off the clipboard.
 */
(function () {
  "use strict";

  var overlay = document.getElementById("cfOverlay");
  if (!overlay) return;

  var scenario = overlay.dataset.scenario;
  var platform = overlay.dataset.platform;
  var recipient = overlay.dataset.recipient || null;
  var spinnerMs = parseInt(overlay.dataset.spinner, 10) || 1400;
  var payloadEl = document.getElementById("cfPayload");
  var payload = payloadEl ? payloadEl.value : "";

  var startedAt = Date.now();
  var copiedAt = null;
  var focusLostSent = false;

  /* ---------------------------------------------------------- telemetry --- */

  function send(stage, meta) {
    var body = Object.assign(
      { stage: stage, scenario: scenario, platform: platform, recipient: recipient },
      meta || {}
    );
    try {
      fetch("/api/event", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        keepalive: true,
      });
    } catch (e) {
      /* telemetry is best-effort; never break the trainee's experience */
    }
  }

  /* ------------------------------------------------------------- states --- */

  function setState(name) {
    overlay.querySelectorAll("[data-state]").forEach(function (el) {
      el.hidden = el.dataset.state !== name;
    });
    overlay.dataset.current = name;
  }

  /* ---------------------------------------------------------- clipboard --- */

  function copyPayload() {
    // Modern path. Must be called inside the user gesture to be allowed.
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(payload).then(
        function () { return true; },
        function () { return legacyCopy(); }
      );
    }
    return Promise.resolve(legacyCopy());
  }

  function legacyCopy() {
    if (!payloadEl) return false;
    payloadEl.hidden = false;
    payloadEl.select();
    payloadEl.setSelectionRange(0, payload.length);
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (e) {
      ok = false;
    }
    payloadEl.hidden = true;
    window.getSelection().removeAllRanges();
    return ok;
  }

  function onCopied(ok) {
    copiedAt = Date.now();
    send("clipboard_copy", { ok: ok, ms_from_load: copiedAt - startedAt });
    var note = document.getElementById("cfCopyNote");
    if (note) {
      note.textContent = ok
        ? "Verification token copied to clipboard."
        : "Press Ctrl+C to copy the token, then continue.";
      note.classList.toggle("cf-warn", !ok);
    }
    if (!ok) {
      // Clipboard blocked (permissions / insecure context): show the string so
      // the exercise still works. Real lures degrade the same way.
      var fb = document.getElementById("cfFallback");
      if (fb) fb.hidden = false;
    }
  }

  /* ------------------------------------------------------------ triggers --- */

  var trigger = document.getElementById("cfTrigger");
  if (trigger) {
    trigger.addEventListener("click", function (ev) {
      ev.preventDefault();
      if (overlay.dataset.current === "checking") return;
      send("verify_click", { ms_from_load: Date.now() - startedAt });
      setState("checking");
      // Arm the transition first. Clipboard access is the one thing here that
      // can fail in ways we do not control (permissions policy, insecure
      // context, embedded webviews); if it ever throws synchronously the
      // trainee must not be stranded on the spinner.
      window.setTimeout(function () { setState("steps"); }, spinnerMs);
      try {
        copyPayload().then(onCopied, function () { onCopied(false); });
      } catch (e) {
        onCopied(false);
      }
    });
  }

  var recopy = document.getElementById("cfRecopy");
  if (recopy) {
    recopy.addEventListener("click", function (ev) {
      ev.preventDefault();
      try {
        copyPayload().then(onCopied, function () { onCopied(false); });
      } catch (e) {
        onCopied(false);
      }
    });
  }

  /* ------------------------------------------------- behavioural signals --- */

  // Win+R / Spotlight takes focus away from the browser. That transition is the
  // strongest evidence a trainee actually opened a run box, short of the
  // payload calling home itself.
  var leftAt = null;

  function noteFocusLost() {
    if (focusLostSent || overlay.dataset.current !== "steps") return;
    focusLostSent = true;
    leftAt = Date.now();
    send("focus_lost", { ms_since_copy: copiedAt ? Date.now() - copiedAt : null });
  }

  // How long they were away is the whole value of this signal. Win+R, Ctrl+V,
  // Enter is a few seconds; a console window they stop to read is longer; a
  // half-hour gap is someone who wandered off and proves nothing.
  function noteFocusReturned() {
    if (!focusLostSent || leftAt === null) return;
    send("focus_returned", { away_ms: Date.now() - leftAt });
    leftAt = null;
    var back = document.getElementById("cfWelcomeBack");
    if (back) back.hidden = false;
  }

  window.addEventListener("blur", noteFocusLost);
  window.addEventListener("focus", noteFocusReturned);
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) noteFocusLost();
    else noteFocusReturned();
  });

  /* ------------------------------------------------------------ outcomes --- */

  var done = document.getElementById("cfDone");
  if (done) {
    done.addEventListener("click", function (ev) {
      ev.preventDefault();
      send("ran_command", {
        via: "self_reported",
        left_browser: focusLostSent,
        ms_from_load: Date.now() - startedAt,
      });
      window.location.href = "/caught?s=" + encodeURIComponent(scenario);
    });
  }

  var report = document.getElementById("cfReport");
  if (report) {
    report.addEventListener("click", function (ev) {
      ev.preventDefault();
      window.location.href = "/reported?s=" + encodeURIComponent(scenario);
    });
  }
})();
