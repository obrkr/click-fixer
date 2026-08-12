"""Flask application for the ClickFix awareness simulator."""

from __future__ import annotations

import csv
import io
import secrets
from functools import wraps

from flask import (
    Flask,
    Response,
    abort,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from .config import (
    DECOY_TAIL,
    RUN_DIALOG_MAX,
    SIG_LEN,
    Config,
    build_payload,
    run_dialog_fit,
    verify_execution_token,
)
from .scenarios import SCENARIOS, STEPS, get_scenario
from .store import STAGE_LABELS, STAGE_ORDER, EventStore

SESSION_COOKIE = "cfsim_sid"
ADMIN_COOKIE = "cfsim_admin"


def create_app(cfg: Config | None = None) -> Flask:
    cfg = cfg or Config.from_env()
    app = Flask(__name__)
    app.secret_key = cfg.secret_key
    app.config["CFSIM"] = cfg
    store = EventStore(cfg.db_path)
    app.config["CFSIM_STORE"] = store

    # ---------------------------------------------------------------- session

    @app.before_request
    def _attach_session() -> None:
        sid = request.cookies.get(SESSION_COOKIE)
        if not sid:
            # 8 chars (48 bits). Short because it is carried inside the payload,
            # where every character competes with RUN_DIALOG_MAX.
            sid = secrets.token_urlsafe(6)
            g.set_session_cookie = True
        g.sid = sid
        # Operators can tag a link per recipient: /s/human_check?t=alice
        g.recipient = request.args.get("t")

    @app.after_request
    def _persist_session(resp: Response) -> Response:
        if getattr(g, "set_session_cookie", False):
            resp.set_cookie(
                SESSION_COOKIE, g.sid, max_age=60 * 60 * 12, samesite="Lax", httponly=True
            )
        # A training host should never end up in a search index.
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        # Watermark every response, so anyone who finds this host mid-campaign —
        # a curious trainee, an analyst triaging a report, a threat hunter — can
        # tell in one header that it is a sanctioned simulation and who owns it.
        resp.headers["X-Training-Simulation"] = "clickfix-sim; authorised awareness training"
        resp.headers["X-Training-Contact"] = cfg.security_contact
        return resp

    def _platform() -> str:
        ua = (request.user_agent.string or "").lower()
        if "windows" in ua:
            return "windows"
        if "mac" in ua or "darwin" in ua:
            return "unix"
        if "linux" in ua and "android" not in ua:
            return "unix"
        return "windows"

    # ------------------------------------------------------------- operator UI

    @app.route("/")
    def console():
        length, fits = run_dialog_fit(cfg)
        return render_template(
            "console.html",
            cfg=cfg,
            scenarios=SCENARIOS.values(),
            admin_token=cfg.admin_token,
            payload_length=length,
            payload_fits=fits,
            run_dialog_max=RUN_DIALOG_MAX,
        )

    @app.route("/robots.txt")
    def robots():
        return Response("User-agent: *\nDisallow: /\n", mimetype="text/plain")

    @app.route("/health")
    def health():
        return jsonify(status="ok", scenarios=list(SCENARIOS))

    # ------------------------------------------------------------------ lures

    @app.route("/s/<scenario_id>")
    def lure(scenario_id: str):
        scenario = get_scenario(scenario_id)
        if scenario is None:
            abort(404)

        platform = _platform()
        store.record(
            g.sid,
            "lure_view",
            scenario=scenario.id,
            recipient=g.recipient,
            platform=platform,
            meta={"ua": request.user_agent.string[:200]},
        )

        payload = build_payload(cfg, g.sid, platform)
        return render_template(
            scenario.lure_template,
            scenario=scenario,
            cfg=cfg,
            steps=STEPS[platform],
            platform=platform,
            payload=payload,
            session_id=g.sid,
            recipient=g.recipient or "",
        )

    @app.route("/api/event", methods=["POST"])
    def api_event():
        data = request.get_json(silent=True) or {}
        stage = data.get("stage")
        try:
            store.record(
                g.sid,
                stage,
                scenario=data.get("scenario"),
                recipient=data.get("recipient") or g.recipient,
                platform=data.get("platform"),
                meta={k: v for k, v in data.items() if k not in {"stage", "scenario", "recipient", "platform"}},
            )
        except ValueError:
            return jsonify(ok=False, error="unknown stage"), 400
        return jsonify(ok=True)

    def _split_code(code: str) -> tuple[str, str]:
        """Split a callback code back into session id and signature."""
        if len(code) <= SIG_LEN:
            return code, ""
        return code[:-SIG_LEN], code[-SIG_LEN:]

    @app.route("/r/<code>")
    def beacon(code: str):
        """Callback fired by the payload itself — the proof of execution.

        A web page cannot see the Run dialog, so everything the browser reports
        is inference. This endpoint is the exception: it can only be reached by
        something running on the trainee's machine. The path is kept short
        because it is embedded in a payload with 259 characters to spend.
        """
        sid, sig = _split_code(code)
        if not sid or not sig:
            return jsonify(ok=False), 400
        verified = verify_execution_token(cfg, sid, sig)
        # An unverified hit is still recorded — losing real execution data is
        # worse than recording it with a caveat — but it never counts as
        # confirmed. Usually it means the server restarted and rotated its key.
        store.record(sid, "ran_command", recipient=g.recipient,
                     platform=_platform(), meta={"via": "beacon", "verified": verified})
        # Deliberately boring: nothing here should spoil the console banner.
        return jsonify(ok=True)

    # --------------------------------------------------------------- outcomes

    @app.route("/caught")
    def caught():
        scenario = get_scenario(request.args.get("s", ""))
        platform = _platform()
        sid = g.sid

        # Execution is recorded by /r when the payload calls home, so this route
        # only ever logs the debrief view — no double counting.
        store.record(sid, "caught_view", scenario=scenario.id if scenario else None,
                     recipient=g.recipient, platform=platform)

        payload = build_payload(cfg, sid, platform)
        return render_template(
            "caught.html",
            cfg=cfg,
            scenario=scenario,
            steps=STEPS[platform],
            platform=platform,
            payload=payload,
            # Shown split apart so the decoy-tail trick is visible at a glance.
            payload_head=payload.replace(DECOY_TAIL, "").rstrip(),
            decoy_tail=DECOY_TAIL,
        )

    @app.route("/reported")
    def reported():
        scenario = get_scenario(request.args.get("s", ""))
        store.record(g.sid, "reported", scenario=scenario.id if scenario else None,
                     recipient=g.recipient, platform=_platform())
        return render_template("reported.html", cfg=cfg, scenario=scenario)

    # ------------------------------------------------------------------ admin

    def require_admin(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            token = request.args.get("token") or request.cookies.get(ADMIN_COOKIE)
            if not token or not secrets.compare_digest(token, cfg.admin_token):
                abort(403, "Invalid or missing admin token.")
            resp = make_response(fn(*args, **kwargs))
            resp.set_cookie(ADMIN_COOKIE, cfg.admin_token, samesite="Lax", httponly=True)
            return resp

        return wrapper

    @app.route("/admin")
    @require_admin
    def admin():
        return render_template(
            "dashboard.html",
            cfg=cfg,
            summary=store.summary(),
            sessions=store.sessions(),
            stage_labels=STAGE_LABELS,
            stage_order=STAGE_ORDER,
            scenarios=SCENARIOS,
        )

    @app.route("/admin/export.csv")
    @require_admin
    def export_csv():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            ["session_id", "recipient", "scenario", "platform", "first_seen",
             "last_seen", "furthest_stage", "compromised", "evidence", "reported",
             "seconds_to_copy", "seconds_away"]
        )
        for s in store.sessions():
            writer.writerow(
                [s["session_id"], s["recipient"] or "", s["scenario"] or "",
                 s["platform"] or "", s["first_seen"], s["last_seen"],
                 STAGE_LABELS.get(s["furthest"], s["furthest"]),
                 int(s["compromised"]), s["evidence"], int(s["reported"]),
                 s["seconds_to_copy"] if s["seconds_to_copy"] is not None else "",
                 s["away_ms"] // 1000 if s["away_ms"] is not None else ""]
            )
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=clickfix-campaign.csv"},
        )

    @app.route("/admin/reset", methods=["POST"])
    @require_admin
    def admin_reset():
        store.reset()
        return redirect(url_for("admin"))

    return app
