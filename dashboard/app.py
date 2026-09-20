"""
Bot Dashboard
------------------------
Public landing page -> Discord OAuth login (allowlisted user IDs) ->
dashboard home (usage analytics + module cards) -> per-module pages.
"""

import os
import sys
import json
import time
import secrets
import shutil
import subprocess
from datetime import datetime
from functools import wraps
from urllib.parse import urlencode

import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)  # so `import economy...` resolves from this file too

from economy.services import permission_service as ps
from economy.services import balance_service as bs
from economy.services import games_service as gsvc
from economy.services import income_service as isvc
from economy.services import registry_service as reg
from economy.db import init_db as economy_init_db, DB_PATH
from guild_paths import guild_file

economy_init_db()  # safe to call every startup - additive, never drops tables
load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY", "change-me-in-env")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("DASHBOARD_COOKIE_SECURE", "0") == "1",
)

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = os.environ.get("GUILD_ID", "1535372103593894028")
BOT_NAME = os.environ.get("BOT_NAME", "Imperial Command System")

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "http://localhost:5000/callback")
# Discord's Administrator permission bit. Override this with a narrower
# permission integer in .env if the public bot should not be an administrator.
BOT_INVITE_PERMISSIONS = os.environ.get("BOT_INVITE_PERMISSIONS", "8")
REVIEW_INVITE_MAX_AGE = int(os.environ.get("REVIEW_INVITE_MAX_AGE", "86400"))

ALLOWED_USER_IDS = {
    uid.strip() for uid in os.environ.get("DASHBOARD_ALLOWED_USER_IDS", "").split(",") if uid.strip()
}

# Can approve/deny community access requests. Defaults to the same set as
# ALLOWED_USER_IDS if unset, so nothing changes for you today - this is
# split out as its own concept for when it needs to diverge later (e.g. a
# moderator who can manage your own dashboard but not approve other
# communities).
SUPER_ADMIN_USER_IDS = {
    uid.strip() for uid in os.environ.get("SUPER_ADMIN_USER_IDS", os.environ.get("DASHBOARD_ALLOWED_USER_IDS", "")).split(",") if uid.strip()
}

PERMISSIONS_FILE = os.path.join(BASE_DIR, "permissions_config.json")
TOGGLES_FILE = os.path.join(BASE_DIR, "command_toggles.json")
USAGE_FILE = os.path.join(BASE_DIR, "usage_data.json")
ROADMAP_FILE = os.path.join(BASE_DIR, "roadmap_data.json")
TASKBOARD_FILE = os.path.join(BASE_DIR, "taskboard_data.json")
PARTNER_FILE = os.path.join(BASE_DIR, "partner_data.json")
SERVER_CONFIG_FILE = os.path.join(BASE_DIR, "server_config.json")
BOT_LOGS_FILE = os.path.join(BASE_DIR, "bot_logs.json")
WEBHOOKS_FILE = os.path.join(BASE_DIR, "dashboard_webhooks.json")
MAINTENANCE_FILE = os.path.join(BASE_DIR, "maintenance.json")

# Every command in the bot, grouped by module for the permissions page.
# Keep in sync when new commands/cogs are added.
COMMAND_GROUPS = {
    "announcements": ["scannounce"],
    "archive": ["archive history", "archive pins", "archive setchannel"],
    "blocker": ["blocker add", "blocker clear", "blocker resolve", "blocker show"],
    "broadcast": ["broadcast cancel", "broadcast list", "broadcast schedule"],
    "devlog": ["devlog"],
    "fun": ["duel", "holonet", "imperial-id", "wanted", "shoutout"],
    "expense": ["expense add", "expense clear", "expense remove", "expense show"],
    "inactivity": ["inactivity"],
    "partner": ["partner add", "partner clear", "partner remove", "partner show"],
    "promote & rank": ["promote", "rank link", "rank links", "rank unlink"],
    "revenue": ["revenue clear", "revenue log", "revenue remove", "revenue show"],
    "roadmap": ["roadmap add", "roadmap clear", "roadmap move", "roadmap remove", "roadmap show"],
    "taskboard": ["taskboard add", "taskboard clear", "taskboard mytasks", "taskboard remove", "taskboard show", "taskboard update"],
    "team": ["team add", "team clear", "team remove", "team show"],
    "testflight": ["testflight add", "testflight clear", "testflight remove", "testflight show", "testflight update"],
    "misc": ["timezone"],
    "versionlog": ["versionlog clear", "versionlog history", "versionlog set", "versionlog show"],
}
ALL_COMMANDS = [cmd for group in COMMAND_GROUPS.values() for cmd in group]

ROADMAP_AREAS = {
    "discord_dev": "🤖 Discord Development",
    "game_dev": "🎮 Game Development",
    "general": "📋 General",
}
ROADMAP_STATUSES = {
    "planned": "🗓️ Planned",
    "in_progress": "🚧 In Progress",
    "done": "✅ Done",
}

_roles_cache = {"data": None, "fetched_at": 0}
_members_cache = {"data": None, "fetched_at": 0}
_channels_cache = {"data": None, "fetched_at": 0}
_bot_identity_cache = {"id": None, "checked_at": 0}
_login_attempts: dict[str, list[float]] = {}
LOGIN_WINDOW_SECONDS = 300
MAX_LOGIN_ATTEMPTS = 10


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def login_rate_limited(client_key: str) -> bool:
    now = time.time()
    attempts = [timestamp for timestamp in _login_attempts.get(client_key, []) if now - timestamp < LOGIN_WINDOW_SECONDS]
    attempts.append(now)
    _login_attempts[client_key] = attempts
    return len(attempts) > MAX_LOGIN_ATTEMPTS


def get_main_bot_id() -> str | None:
    """Return the application/user ID belonging to DISCORD_TOKEN."""
    if not DISCORD_TOKEN:
        return None
    if _bot_identity_cache["id"] and time.time() - _bot_identity_cache["checked_at"] < 300:
        return _bot_identity_cache["id"]
    try:
        response = requests.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {DISCORD_TOKEN}"},
            timeout=10,
        )
        response.raise_for_status()
        bot_id = response.json().get("id")
        _bot_identity_cache["id"] = bot_id
        _bot_identity_cache["checked_at"] = time.time()
        return bot_id
    except requests.RequestException:
        return None


def oauth_matches_main_bot() -> tuple[bool, str | None]:
    main_bot_id = get_main_bot_id()
    if not main_bot_id:
        return False, "The main bot token could not be verified."
    if not DISCORD_CLIENT_ID:
        return False, "DISCORD_CLIENT_ID is not configured."
    if DISCORD_CLIENT_ID != main_bot_id:
        return False, "DISCORD_CLIENT_ID belongs to a different Discord application."
    return True, None


def fetch_guild_channels() -> list[dict]:
    """Text channels for GUILD_ID, fetched using the bot's own token. Cached for 60s."""
    if _channels_cache["data"] is not None and (time.time() - _channels_cache["fetched_at"]) < 60:
        return _channels_cache["data"]
    if not DISCORD_TOKEN:
        return []
    try:
        resp = requests.get(
            f"https://discord.com/api/v10/guilds/{current_guild_id()}/channels",
            headers={"Authorization": f"Bot {DISCORD_TOKEN}"},
            timeout=10,
        )
        resp.raise_for_status()
        channels = [c for c in resp.json() if c["type"] == 0]  # 0 = text channel
        channels.sort(key=lambda c: c.get("position", 0))
        _channels_cache["data"] = channels
        _channels_cache["fetched_at"] = time.time()
        return channels
    except Exception as e:
        print(f"⚠️ Failed to fetch guild channels: {e}")
        return _channels_cache["data"] or []


def fetch_guild_members() -> list[dict]:
    """Members for GUILD_ID, fetched using the bot's own token. Cached for 60s."""
    if _members_cache["data"] is not None and (time.time() - _members_cache["fetched_at"]) < 60:
        return _members_cache["data"]
    if not DISCORD_TOKEN:
        return []
    try:
        resp = requests.get(
            f"https://discord.com/api/v10/guilds/{current_guild_id()}/members?limit=1000",
            headers={"Authorization": f"Bot {DISCORD_TOKEN}"},
            timeout=10,
        )
        resp.raise_for_status()
        members = []
        for m in resp.json():
            user = m.get("user", {})
            if user.get("bot"):
                continue
            members.append({
                "id": user["id"],
                "name": m.get("nick") or user.get("global_name") or user["username"],
            })
        members.sort(key=lambda m: m["name"].lower())
        _members_cache["data"] = members
        _members_cache["fetched_at"] = time.time()
        return members
    except Exception as e:
        print(f"⚠️ Failed to fetch guild members: {e}")
        return _members_cache["data"] or []


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def fetch_guild_roles() -> list[dict]:
    if _roles_cache["data"] is not None and (time.time() - _roles_cache["fetched_at"]) < 60:
        return _roles_cache["data"]
    if not DISCORD_TOKEN:
        return []
    try:
        resp = requests.get(
            f"https://discord.com/api/v10/guilds/{current_guild_id()}/roles",
            headers={"Authorization": f"Bot {DISCORD_TOKEN}"},
            timeout=10,
        )
        resp.raise_for_status()
        roles = [r for r in resp.json() if r["name"] != "@everyone"]
        roles.sort(key=lambda r: r["position"], reverse=True)
        _roles_cache["data"] = roles
        _roles_cache["fetched_at"] = time.time()
        return roles
    except Exception as e:
        print(f"⚠️ Failed to fetch guild roles: {e}")
        return _roles_cache["data"] or []


def login_required(view):
    """Gate for the existing, single-server dashboard - re-checks the
    allowlist on every request (not just once at login), so it stays exactly
    as protected as before even though /callback now issues a session to
    ANY successfully authenticated Discord user (needed for the new
    request-access flow below)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id or (ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS):
            return redirect(url_for("login"))
        if "guild_id" not in session:
            session["guild_id"] = int(GUILD_ID)
        return view(*args, **kwargs)
    return wrapped


def any_login_required(view):
    """Lighter gate - any successfully authenticated Discord user, used only
    by the request-access flow (not the sensitive dashboard pages)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def current_guild_id() -> int:
    return int(session.get("guild_id", GUILD_ID))


def available_dashboard_guilds() -> list[dict]:
    guilds = session.get("administered_guilds", [])
    if guilds:
        return guilds
    if session.get("user_id") in ALLOWED_USER_IDS:
        return [{"id": str(GUILD_ID), "name": "Primary server"}]
    return []


def selected_guild_file(filename: str) -> str:
    return guild_file(current_guild_id(), filename)


def super_admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id or user_id not in SUPER_ADMIN_USER_IDS:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def owner_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.before_request
def protect_owner_posts():
    if request.method == "POST" and request.path not in {"/callback"}:
        expected = session.get("csrf_token")
        if not expected or not secrets.compare_digest(request.form.get("csrf_token", ""), expected):
            return "Invalid or missing security token.", 400


@app.context_processor
def inject_owner_security():
    return {"owner_csrf_token": owner_csrf_token(), "csrf_token": owner_csrf_token()}


# ---------- public landing ----------

@app.context_processor
def inject_globals():
    """Makes the live bot status and super-admin flag available on every
    page without needing to pass them from each individual route."""
    try:
        status = get_service_status("swbot")
    except Exception:
        status = {"active": None}
    return {
        "global_bot_status": status,
        "is_super_admin": session.get("user_id") in SUPER_ADMIN_USER_IDS,
        "available_dashboard_guilds": available_dashboard_guilds(),
        "selected_guild_id": str(session.get("guild_id", GUILD_ID)),
    }


@app.route("/")
def landing():
    return render_template("landing.html", bot_name=BOT_NAME)


@app.route("/health")
def health_check():
    database_ok = False
    try:
        economy_init_db()
        database_ok = os.path.exists(DB_PATH)
    except Exception:
        pass
    status = get_service_status("swbot")
    healthy = database_ok and status.get("active") is not False
    return {
        "status": "ok" if healthy else "degraded",
        "database": "ok" if database_ok else "error",
        "bot": "online" if status.get("active") else "offline",
    }, 200 if healthy else 503


# ---------- auth ----------

@app.route("/login")
def login():
    if login_rate_limited(request.remote_addr or "unknown"):
        return "Too many login attempts. Please try again later.", 429
    if not DISCORD_CLIENT_ID:
        return "DISCORD_CLIENT_ID isn't set in .env yet - see setup notes.", 500
    matches_main_bot, identity_error = oauth_matches_main_bot()
    if not matches_main_bot:
        return (
            "Dashboard OAuth is not configured for the running main bot. "
            f"{identity_error} Set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET "
            "from the same Discord Developer Portal application as DISCORD_TOKEN.",
            500,
        )
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds",
    }
    session["oauth_state"] = secrets.token_urlsafe(32)
    params["state"] = session["oauth_state"]
    auth_url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"
    return render_template("login.html", auth_url=auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")
    if not code or not state or not secrets.compare_digest(state, session.pop("oauth_state", "")):
        flash("Login was cancelled or failed.", "error")
        return redirect(url_for("login"))

    matches_main_bot, identity_error = oauth_matches_main_bot()
    if not matches_main_bot:
        return (
            "Dashboard OAuth is not configured for the running main bot. "
            f"{identity_error} Update the VM's DISCORD_CLIENT_ID and "
            "DISCORD_CLIENT_SECRET values.",
            500,
        )

    token_resp = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    if token_resp.status_code != 200:
        flash("Discord login failed. Try again.", "error")
        return redirect(url_for("login"))

    access_token = token_resp.json()["access_token"]
    user_resp = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    user = user_resp.json()
    user_id = user["id"]

    session["user_id"] = user_id
    session["username"] = user.get("username", "Unknown")

    if ALLOWED_USER_IDS and user_id in ALLOWED_USER_IDS:
        return redirect(url_for("dashboard_home"))

    # Not an existing owner - fetch the servers they administer (owner or
    # has the Administrator permission) for the request-access picker.
    ADMINISTRATOR_BIT = 0x8
    try:
        guilds_resp = requests.get(
            "https://discord.com/api/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        guilds = guilds_resp.json() if guilds_resp.status_code == 200 else []
    except Exception:
        guilds = []

    admin_guilds = []
    for g in guilds:
        try:
            perms = int(g.get("permissions", 0))
        except (TypeError, ValueError):
            perms = 0
        if g.get("owner") or (perms & ADMINISTRATOR_BIT):
            admin_guilds.append({"id": g["id"], "name": g["name"]})

    session["administered_guilds"] = admin_guilds
    return redirect(url_for("request_access_page"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/select-server/<int:guild_id>")
@login_required
def select_server(guild_id):
    allowed_ids = {int(guild["id"]) for guild in available_dashboard_guilds()}
    if guild_id not in allowed_ids:
        flash("You do not administer that server.", "error")
        return redirect(url_for("dashboard_home"))
    session["guild_id"] = guild_id
    return redirect(request.referrer or url_for("dashboard_home"))


# ---------- dashboard home ----------

@app.route("/dashboard")
@login_required
def dashboard_home():
    usage = load_json(selected_guild_file("usage_data.json"), {})
    sorted_usage = sorted(usage.items(), key=lambda kv: kv[1]["count"], reverse=True)[:10]

    top_commands = []
    for cmd, stats in sorted_usage:
        last_used_display = "-"
        if stats.get("last_used"):
            last_used_display = datetime.fromtimestamp(stats["last_used"]).strftime("%b %d, %H:%M")
        top_commands.append((cmd, {**stats, "last_used_display": last_used_display}))

    # Build last-7-days totals across ALL commands for the chart
    from datetime import timedelta
    today = datetime.now().date()
    day_labels = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    day_totals = {d: 0 for d in day_labels}
    for stats in usage.values():
        for day, count in stats.get("daily", {}).items():
            if day in day_totals:
                day_totals[day] += count

    return render_template(
        "dashboard_home.html",
        username=session.get("username"),
        active_tab="home",
        top_commands=top_commands,
        chart_labels=[d[5:] for d in day_labels],  # MM-DD
        chart_values=[day_totals[d] for d in day_labels],
    )


# ---------- permissions ----------

@app.route("/permissions", methods=["GET", "POST"])
@login_required
def permissions_page():
    data = load_json(selected_guild_file("permissions_config.json"), {})
    toggles = load_json(selected_guild_file("command_toggles.json"), {})
    roles = fetch_guild_roles()

    if request.method == "POST":
        new_data = {}
        new_toggles = {}
        for command in ALL_COMMANDS:
            field_name = f"roles_{command.replace(' ', '_').replace('-', '_')}"
            enabled_field = f"enabled_{command.replace(' ', '_').replace('-', '_')}"

            selected = request.form.getlist(field_name)
            if selected:
                new_data[command] = selected

            new_toggles[command] = enabled_field in request.form

        save_json(selected_guild_file("permissions_config.json"), new_data)
        save_json(selected_guild_file("command_toggles.json"), new_toggles)
        flash("Saved - takes effect immediately, no restart needed.", "success")
        return redirect(url_for("permissions_page"))

    groups = {}
    for group_name, commands in COMMAND_GROUPS.items():
        rows = []
        for command in commands:
            field_name = f"roles_{command.replace(' ', '_').replace('-', '_')}"
            enabled_field = f"enabled_{command.replace(' ', '_').replace('-', '_')}"
            rows.append({
                "command": command,
                "field_name": field_name,
                "enabled_field": enabled_field,
                "current_ids": set(data.get(command, [])),
                "enabled": toggles.get(command, True),
            })
        groups[group_name] = rows

    return render_template(
        "permissions.html",
        groups=groups,
        roles=roles,
        username=session.get("username"),
        active_tab="permissions",
        roles_fetch_failed=not roles and DISCORD_TOKEN,
    )


# ---------- roadmap ----------

def load_roadmap() -> dict:
    return load_json(selected_guild_file("roadmap_data.json"), {"items": [], "channel_id": None, "message_id": None})


def save_roadmap(data: dict):
    save_json(selected_guild_file("roadmap_data.json"), data)


@app.route("/roadmap")
@login_required
def roadmap_page():
    data = load_roadmap()
    items_by_area = {}
    for idx, item in enumerate(data["items"]):
        items_by_area.setdefault(item["area"], []).append({**item, "id": idx})

    return render_template(
        "roadmap.html",
        areas=ROADMAP_AREAS,
        statuses=ROADMAP_STATUSES,
        items_by_area=items_by_area,
        username=session.get("username"),
        active_tab="roadmap",
    )


@app.route("/roadmap/add", methods=["POST"])
@login_required
def roadmap_add():
    data = load_roadmap()
    data["items"].append({
        "area": request.form["area"],
        "status": request.form["status"],
        "text": request.form["text"].strip(),
    })
    save_roadmap(data)
    flash("Added.", "success")
    return redirect(url_for("roadmap_page"))


@app.route("/roadmap/<int:item_id>/move", methods=["POST"])
@login_required
def roadmap_move(item_id):
    data = load_roadmap()
    if 0 <= item_id < len(data["items"]):
        data["items"][item_id]["status"] = request.form["status"]
        save_roadmap(data)
        flash("Moved.", "success")
    return redirect(url_for("roadmap_page"))


@app.route("/roadmap/<int:item_id>/remove", methods=["POST"])
@login_required
def roadmap_remove(item_id):
    data = load_roadmap()
    if 0 <= item_id < len(data["items"]):
        data["items"].pop(item_id)
        save_roadmap(data)
        flash("Removed.", "success")
    return redirect(url_for("roadmap_page"))


# ---------- taskboard ----------

TASKBOARD_STATUS_LABELS = {"todo": "⬜ To Do", "in_progress": "🟦 In Progress", "done": "✅ Done"}
TASKBOARD_STATUS_ORDER = {"in_progress": 0, "todo": 1, "done": 2}


def load_taskboard() -> dict:
    return load_json(selected_guild_file("taskboard_data.json"), {"tasks": [], "channel_id": None, "message_id": None})


def save_taskboard(data: dict):
    save_json(selected_guild_file("taskboard_data.json"), data)


@app.route("/taskboard")
@login_required
def taskboard_page():
    data = load_taskboard()
    members = fetch_guild_members()
    member_names = {m["id"]: m["name"] for m in members}

    by_assignee = {}
    for idx, task in enumerate(data["tasks"]):
        by_assignee.setdefault(task["assignee_id"], []).append({**task, "id": idx})
    for tasks in by_assignee.values():
        tasks.sort(key=lambda t: TASKBOARD_STATUS_ORDER.get(t["status"], 99))

    return render_template(
        "taskboard.html",
        username=session.get("username"),
        active_tab="taskboard",
        members=members,
        member_names=member_names,
        by_assignee=by_assignee,
        status_labels=TASKBOARD_STATUS_LABELS,
    )


@app.route("/taskboard/add", methods=["POST"])
@login_required
def taskboard_add():
    data = load_taskboard()
    data["tasks"].append({
        "assignee_id": int(request.form["assignee_id"]),
        "text": request.form["text"].strip(),
        "status": "todo",
    })
    save_taskboard(data)
    flash("Task added.", "success")
    return redirect(url_for("taskboard_page"))


@app.route("/taskboard/<int:task_id>/status", methods=["POST"])
@login_required
def taskboard_status(task_id):
    data = load_taskboard()
    if 0 <= task_id < len(data["tasks"]):
        data["tasks"][task_id]["status"] = request.form["status"]
        save_taskboard(data)
        flash("Updated.", "success")
    return redirect(url_for("taskboard_page"))


@app.route("/taskboard/<int:task_id>/remove", methods=["POST"])
@login_required
def taskboard_remove(task_id):
    data = load_taskboard()
    if 0 <= task_id < len(data["tasks"]):
        data["tasks"].pop(task_id)
        save_taskboard(data)
        flash("Removed.", "success")
    return redirect(url_for("taskboard_page"))


def fetch_member_role_ids(user_id: str) -> list[int]:
    """Roles for one specific member - used by the Test Permission tool.
    Not cached since it's only called on-demand, not on every page load."""
    if not DISCORD_TOKEN:
        return []
    try:
        resp = requests.get(
            f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{user_id}",
            headers={"Authorization": f"Bot {DISCORD_TOKEN}"},
            timeout=10,
        )
        resp.raise_for_status()
        return [int(r) for r in resp.json().get("roles", [])]
    except Exception as e:
        print(f"⚠️ Failed to fetch member roles: {e}")
        return []


# ---------- economy permissions ----------

@app.route("/economy/permissions", methods=["GET"])
@login_required
def economy_permissions_page():
    rules = ps.list_rules(current_guild_id())
    roles = fetch_guild_roles()
    members = fetch_guild_members()
    channels = fetch_guild_channels()
    role_names = {str(r["id"]): r["name"] for r in roles}
    member_names = {str(m["id"]): m["name"] for m in members}
    channel_names = {str(c["id"]): c["name"] for c in channels}

    def label_for(rule):
        names = {"user": member_names, "role": role_names, "channel": channel_names}.get(rule.target_type, {})
        return names.get(str(rule.target_id), f"ID {rule.target_id}")

    rule_rows = [{"rule": r, "target_label": label_for(r)} for r in rules]
    role_presets = ps.get_role_presets(current_guild_id())

    return render_template(
        "economy_permissions.html",
        username=session.get("username"),
        active_tab="economy_permissions",
        rule_rows=rule_rows,
        roles=roles,
        members=members,
        channels=channels,
        role_presets=role_presets,
        role_names=role_names,
        preset_names=list(ps.PRESETS.keys()),
        admin_commands=sorted(ps.ECONOMY_ADMIN_COMMANDS),
    )


@app.route("/economy/permissions/add-rule", methods=["POST"])
@login_required
def economy_add_rule():
    target_type = request.form["target_type"]
    target_id = int(request.form["target_id"])
    rule_type = request.form["rule_type"]
    command_or_category = request.form["command_or_category"]
    effect = request.form["effect"]

    ps.add_rule(current_guild_id(), rule_type, target_type, target_id, command_or_category, effect, int(session["user_id"]))
    flash("Rule added.", "success")
    return redirect(url_for("economy_permissions_page"))


@app.route("/economy/permissions/remove-rule/<int:rule_id>", methods=["POST"])
@login_required
def economy_remove_rule(rule_id):
    ps.remove_rule(current_guild_id(), rule_id, int(session["user_id"]))
    flash("Rule removed.", "success")
    return redirect(url_for("economy_permissions_page"))


@app.route("/economy/permissions/apply-preset", methods=["POST"])
@login_required
def economy_apply_preset():
    role_id = int(request.form["role_id"])
    preset_name = request.form["preset_name"]
    ps.apply_preset(current_guild_id(), role_id, preset_name, int(session["user_id"]))
    flash(f"Applied '{preset_name}' to the role.", "success")
    return redirect(url_for("economy_permissions_page"))


@app.route("/economy/permissions/test", methods=["GET", "POST"])
@login_required
def economy_permission_test_page():
    result = None
    if request.method == "POST":
        member_id = int(request.form["member_id"])
        command = request.form["command"]
        channel_id = request.form.get("channel_id")
        role_ids = fetch_member_role_ids(str(member_id))
        result = ps.check_permission(
            current_guild_id(), member_id, role_ids, command,
            channel_id=int(channel_id) if channel_id else None,
        )

    return render_template(
        "economy_permission_test.html",
        username=session.get("username"),
        active_tab="economy_permissions",
        members=fetch_guild_members(),
        channels=fetch_guild_channels(),
        commands=sorted(ps.ECONOMY_ADMIN_COMMANDS) + ["balance", "pay", "deposit", "withdraw"],
        result=result,
    )


@app.route("/economy/audit-log")
@login_required
def economy_audit_log_page():
    logs = ps.get_audit_log(current_guild_id())
    return render_template(
        "economy_audit_log.html",
        username=session.get("username"),
        active_tab="economy_permissions",
        logs=logs,
    )


# ---------- games config ----------

@app.route("/economy/games", methods=["GET", "POST"])
@login_required
def economy_games_page():
    if request.method == "POST":
        for game in gsvc.DEFAULT_CONFIGS:
            gsvc.set_game_config(
                current_guild_id(), game,
                min_bet=int(request.form.get(f"min_bet_{game}", 10)),
                max_bet=int(request.form.get(f"max_bet_{game}", 10000)),
                cooldown_seconds=int(request.form.get(f"cooldown_{game}", 3)),
                enabled=f"enabled_{game}" in request.form,
            )
        flash("Game settings saved - takes effect immediately.", "success")
        return redirect(url_for("economy_games_page"))

    configs = gsvc.list_game_configs(current_guild_id())
    return render_template(
        "economy_games.html",
        username=session.get("username"),
        active_tab="economy_games",
        configs=configs,
    )


# ---------- income config ----------

@app.route("/economy/income", methods=["GET", "POST"])
@login_required
def economy_income_page():
    if request.method == "POST":
        for cmd in isvc.DEFAULT_INCOME_CONFIGS:
            isvc.set_income_config(
                current_guild_id(), cmd,
                min_payout=int(request.form.get(f"min_{cmd}", 0)),
                max_payout=int(request.form.get(f"max_{cmd}", 0)),
                cooldown_seconds=int(request.form.get(f"cooldown_{cmd}", 3600)),
                success_chance=float(request.form.get(f"chance_{cmd}", 1.0)),
                fine_amount=int(request.form.get(f"fine_{cmd}", 0)),
                enabled=f"enabled_{cmd}" in request.form,
            )
        flash("Income settings saved - takes effect immediately.", "success")
        return redirect(url_for("economy_income_page"))

    configs = isvc.list_income_configs(current_guild_id())
    return render_template(
        "economy_income.html",
        username=session.get("username"),
        active_tab="economy_income",
        configs=configs,
    )


@app.route("/economy/chat-money", methods=["GET", "POST"])
@login_required
def economy_chat_money_page():
    if request.method == "POST":
        isvc.set_chat_money_config(
            current_guild_id(),
            enabled="enabled" in request.form,
            min_amount=int(request.form.get("min_amount", 1)),
            max_amount=int(request.form.get("max_amount", 5)),
            cooldown_seconds=int(request.form.get("cooldown_seconds", 60)),
            excluded_channels=",".join(request.form.getlist("excluded_channels")),
            excluded_roles=",".join(request.form.getlist("excluded_roles")),
        )
        flash("Chat money settings saved.", "success")
        return redirect(url_for("economy_chat_money_page"))

    config = isvc.get_chat_money_config(current_guild_id())
    return render_template(
        "economy_chat_money.html",
        username=session.get("username"),
        active_tab="economy_income",
        config=config,
        channels=fetch_guild_channels(),
        roles=fetch_guild_roles(),
        excluded_channel_ids=set(config.excluded_channels.split(",")) if config.excluded_channels else set(),
        excluded_role_ids=set(config.excluded_roles.split(",")) if config.excluded_roles else set(),
    )


@app.route("/economy/role-income", methods=["GET"])
@login_required
def economy_role_income_page():
    from economy.db import SessionLocal
    from economy.models import RoleIncome
    with SessionLocal() as db_session:
        rules = db_session.query(RoleIncome).filter_by(guild_id=current_guild_id()).all()
    return render_template(
        "economy_role_income.html",
        username=session.get("username"),
        active_tab="economy_income",
        rules=rules,
        roles=fetch_guild_roles(),
    )


@app.route("/economy/role-income/add", methods=["POST"])
@login_required
def economy_role_income_add():
    from economy.db import SessionLocal
    from economy.models import RoleIncome
    with SessionLocal() as db_session:
        db_session.add(RoleIncome(
            guild_id=current_guild_id(),
            role_id=int(request.form["role_id"]),
            amount=int(request.form["amount"]),
            interval_hours=int(request.form["interval_hours"]),
            enabled=True,
        ))
        db_session.commit()
    flash("Role income rule added.", "success")
    return redirect(url_for("economy_role_income_page"))


@app.route("/economy/role-income/<int:rule_id>/remove", methods=["POST"])
@login_required
def economy_role_income_remove(rule_id):
    from economy.db import SessionLocal
    from economy.models import RoleIncome
    with SessionLocal() as db_session:
        rule = db_session.query(RoleIncome).filter_by(id=rule_id, guild_id=current_guild_id()).one_or_none()
        if rule:
            db_session.delete(rule)
            db_session.commit()
    flash("Role income rule removed.", "success")
    return redirect(url_for("economy_role_income_page"))


# ---------- request access (new communities) ----------

@app.route("/request-access", methods=["GET", "POST"])
@any_login_required
def request_access_page():
    # Existing allowlisted owners don't need this flow
    if ALLOWED_USER_IDS and session["user_id"] in ALLOWED_USER_IDS:
        return redirect(url_for("dashboard_home"))

    if request.method == "POST":
        guild_id = int(request.form["guild_id"])
        admin_guilds = session.get("administered_guilds", [])
        match = next((g for g in admin_guilds if g["id"] == str(guild_id)), None)
        if match is None:
            flash("That server isn't in your administered-servers list. Log in again if it's missing.", "error")
            return redirect(url_for("request_access_page"))

        reg.request_access(
            guild_id=guild_id,
            guild_name=match["name"],
            owner_discord_id=int(session["user_id"]),
            owner_discord_name=session["username"],
            note=request.form.get("note", "").strip() or None,
        )
        flash("Request submitted. You'll be able to check its status here.", "success")
        return redirect(url_for("request_access_page"))

    admin_guilds = session.get("administered_guilds", [])
    my_requests = [reg.get_request_for_guild(int(g["id"])) for g in admin_guilds]
    my_requests = [r for r in my_requests if r is not None]

    return render_template(
        "request_access.html",
        username=session.get("username"),
        admin_guilds=admin_guilds,
        my_requests=my_requests,
    )


@app.route("/owner")
@super_admin_required
def owner_dashboard_page():
    servers = reg.list_all()
    logs = load_json(BOT_LOGS_FILE, [])
    recent_logs = []
    for entry in reversed(logs[-8:]):
        recent_logs.append({
            **entry,
            "time_display": datetime.fromtimestamp(entry.get("time", 0)).strftime("%b %d, %H:%M:%S"),
        })

    return render_template(
        "owner_dashboard.html",
        username=session.get("username"),
        active_tab="owner_dashboard",
        stats={
            "total": len(servers),
            "pending": sum(server.status == "pending" for server in servers),
            "review": sum(server.status == "review" for server in servers),
            "approved": sum(server.status == "approved" for server in servers),
            "removed": sum(server.status == "removed" for server in servers),
            "disabled": sum(server.status == "approved" and not server.bot_enabled for server in servers),
        },
        service_status=get_service_status("swbot"),
        recent_logs=recent_logs,
        recent_audit=reg.list_owner_audit(8),
    )


@app.route("/owner/servers")
@super_admin_required
def owner_servers_page():
    query = request.args.get("q", "").strip().lower()
    status = request.args.get("status", "all")
    servers = reg.list_all()
    if query:
        servers = [
            server for server in servers
            if query in server.guild_name.lower()
            or query in str(server.guild_id)
            or query in server.owner_discord_name.lower()
        ]
    if status != "all":
        servers = [server for server in servers if server.status == status]

    return render_template(
        "owner_servers.html",
        username=session.get("username"),
        active_tab="owner_servers",
        servers=servers,
        query=request.args.get("q", ""),
        status=status,
    )


def bot_api_headers() -> dict[str, str]:
    return {"Authorization": f"Bot {DISCORD_TOKEN}"} if DISCORD_TOKEN else {}


def refresh_discovered_servers() -> tuple[int, int]:
    if not DISCORD_TOKEN:
        return 0, 0
    response = requests.get(
        "https://discord.com/api/v10/users/@me/guilds?with_counts=true",
        headers=bot_api_headers(),
        timeout=10,
    )
    response.raise_for_status()
    discovered = 0
    present_ids = set()
    for guild in response.json():
        guild_id = int(guild["id"])
        present_ids.add(guild_id)
        entry = reg.get_request_for_guild(guild_id)
        if entry is None:
            entry = reg.auto_register_pending(
                guild_id,
                guild.get("name", "Unknown server"),
                0,
                "Unknown",
            )
            discovered += 1
        snapshot = json.dumps({
            "name": guild.get("name"),
            "owner_id": guild.get("owner_id"),
            "member_count": guild.get("approximate_member_count"),
            "channel_count": None,
            "role_count": None,
            "permissions": entry.permission_summary or "Not available from dashboard refresh",
        })
        reg.update_presence(
            entry.id,
            True,
            guild.get("name"),
            guild.get("approximate_member_count"),
            None,
            None,
            entry.permission_summary,
            snapshot,
        )

    missing = 0
    for entry in reg.list_all():
        if entry.guild_id not in present_ids and entry.bot_present:
            reg.update_presence(entry.id, False)
            missing += 1
    return discovered, missing


def create_review_invite(guild_id: int) -> tuple[str | None, str | None]:
    if not DISCORD_TOKEN:
        return None, "DISCORD_TOKEN is not configured"
    channels_response = requests.get(
        f"https://discord.com/api/v10/guilds/{guild_id}/channels",
        headers=bot_api_headers(),
        timeout=10,
    )
    if channels_response.status_code != 200:
        return None, f"Could not read server channels ({channels_response.status_code})"
    channels = [channel for channel in channels_response.json() if channel.get("type") == 0]
    if not channels:
        return None, "No text channels available"
    last_error = "Bot lacks Create Invite permission"
    for channel in channels:
        response = requests.post(
            f"https://discord.com/api/v10/channels/{channel['id']}/invites",
            headers={**bot_api_headers(), "Content-Type": "application/json"},
            json={"max_age": REVIEW_INVITE_MAX_AGE, "max_uses": 0, "unique": True, "reason": "Owner Panel review invite"},
            timeout=10,
        )
        if response.status_code == 200:
            return response.json().get("url"), None
        last_error = response.text[:300]
    return None, last_error


def invite_code(invite_url: str | None) -> str | None:
    if not invite_url:
        return None
    return invite_url.rstrip("/").rsplit("/", 1)[-1] or None


@app.route("/owner/servers/refresh", methods=["POST"])
@super_admin_required
def owner_refresh_servers():
    try:
        discovered, missing = refresh_discovered_servers()
        flash(f"Discovery complete: {discovered} new server(s), {missing} server(s) no longer contain the bot.", "success")
    except Exception as e:
        flash(f"Server discovery failed: {e}", "error")
    return redirect(url_for("owner_servers_page"))


@app.route("/owner/servers/<int:registry_id>")
@super_admin_required
def owner_server_detail(registry_id):
    entry = next((server for server in reg.list_all() if server.id == registry_id), None)
    if entry is None:
        flash("Server record not found.", "error")
        return redirect(url_for("owner_servers_page"))
    return render_template(
        "owner_server_detail.html",
        username=session.get("username"),
        active_tab="owner_servers",
        server=entry,
        audit_entries=[audit for audit in reg.list_owner_audit(100) if audit.registry_id == registry_id][:20],
    )


@app.route("/owner/logs")
@super_admin_required
def owner_logs_page():
    query = request.args.get("q", "").strip().lower()
    level = request.args.get("level", "all")
    entries = []
    for entry in reversed(load_json(BOT_LOGS_FILE, [])):
        if level != "all" and entry.get("level") != level:
            continue
        if query and query not in entry.get("message", "").lower():
            continue
        entries.append({
            **entry,
            "time_display": datetime.fromtimestamp(entry.get("time", 0)).strftime("%b %d, %H:%M:%S"),
        })
    return render_template(
        "owner_logs.html",
        username=session.get("username"),
        active_tab="owner_logs",
        logs=entries[:200],
        query=request.args.get("q", ""),
        level=level,
    )


@app.route("/owner/audit")
@super_admin_required
def owner_audit_page():
    return render_template(
        "owner_audit.html",
        username=session.get("username"),
        active_tab="owner_audit",
        entries=reg.list_owner_audit(200),
    )


@app.route("/owner/backup", methods=["POST"])
@super_admin_required
def owner_backup_database():
    backup_dir = os.path.join(BASE_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    backup_name = f"economy-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    backup_path = os.path.join(backup_dir, backup_name)
    try:
        shutil.copy2(DB_PATH, backup_path)
        reg.record_owner_action(int(session["user_id"]), "database_backup", details=backup_name)
        flash(f"Database backup created: {backup_name}", "success")
    except Exception as e:
        flash(f"Database backup failed: {e}", "error")
    return redirect(url_for("owner_dashboard_page"))


def send_discord_dm(user_id: int, content: str) -> bool:
    """Sends a DM using the bot's own token via plain REST calls - no
    running bot process needed for this, just the token. Best-effort:
    returns False (and doesn't raise) if the user has DMs disabled or
    anything else goes wrong, since this should never block an approve/deny
    action from completing."""
    if not DISCORD_TOKEN:
        return False
    try:
        dm_resp = requests.post(
            "https://discord.com/api/v10/users/@me/channels",
            headers={"Authorization": f"Bot {DISCORD_TOKEN}"},
            json={"recipient_id": str(user_id)},
            timeout=10,
        )
        if dm_resp.status_code != 200:
            return False
        channel_id = dm_resp.json()["id"]
        msg_resp = requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {DISCORD_TOKEN}"},
            json={"content": content},
            timeout=10,
        )
        return msg_resp.status_code == 200
    except Exception as e:
        print(f"⚠️ Failed to send Discord DM: {e}")
        return False


def leave_discord_guild(guild_id: int) -> bool:
    """Ask Discord to remove this bot from a guild.

    A 404 means the bot is already gone, which is a successful end state for
    the owner-panel removal flow.
    """
    if not DISCORD_TOKEN:
        return False
    try:
        response = requests.delete(
            f"https://discord.com/api/v10/users/@me/guilds/{guild_id}",
            headers={"Authorization": f"Bot {DISCORD_TOKEN}"},
            timeout=10,
        )
        if response.status_code not in (204, 404):
            print(f"⚠️ Failed to leave Discord guild {guild_id}: {response.status_code} {response.text[:300]}")
            return False
        return True
    except Exception as e:
        print(f"⚠️ Failed to leave Discord guild {guild_id}: {e}")
        return False


def bot_invite_url() -> str | None:
    """Build an invite URL for the bot represented by ``DISCORD_TOKEN``.

    The dashboard OAuth client may be a separate DEV application, so its
    client ID must not be reused for the bot invite. Discord requires a server
    administrator to authorize a bot invite; the bot token cannot accept one
    silently.
    """
    if not DISCORD_TOKEN:
        return None
    try:
        response = requests.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {DISCORD_TOKEN}"},
            timeout=10,
        )
        if response.status_code != 200:
            print(f"⚠️ Failed to identify invite bot: {response.status_code} {response.text[:300]}")
            return None
        bot_id = response.json().get("id")
        if not bot_id:
            return None
        params = urlencode({
            "client_id": bot_id,
            "scope": "bot applications.commands",
            "permissions": BOT_INVITE_PERMISSIONS,
        })
        return f"https://discord.com/oauth2/authorize?{params}"
    except Exception as e:
        print(f"⚠️ Failed to build bot invite URL: {e}")
        return None


@app.route("/owner/servers/<int:registry_id>/decide", methods=["POST"])
@super_admin_required
def owner_decide(registry_id):
    approve = request.form.get("decision") == "approve"
    entry = reg.decide(registry_id, approve, int(session["user_id"]))
    if entry:
        reg.record_owner_action(
            int(session["user_id"]),
            "approved" if approve else "denied",
            entry,
            entry.note or "No review note",
        )
        flash(f"{'Approved' if approve else 'Denied'} {entry.guild_name}.", "success")
        if approve:
            invite_url = bot_invite_url()
            dm_text = (
                f"✅ Your request for **{entry.guild_name}** has been approved! "
                f"To add the bot back to your server, use this link and select **{entry.guild_name}**:\n"
                f"{invite_url or 'The bot invite link is not configured; please contact an administrator.'}\n\n"
                f"After Discord confirms the authorization, log back into the dashboard to manage it."
            )
        else:
            dm_text = f"❌ Your request for **{entry.guild_name}** was denied."
        send_discord_dm(entry.owner_discord_id, dm_text)
    return redirect(url_for("owner_servers_page"))


@app.route("/owner/servers/<int:registry_id>/toggle-enabled", methods=["POST"])
@super_admin_required
def owner_toggle_enabled(registry_id):
    entries = reg.list_all()
    entry = next((e for e in entries if e.id == registry_id), None)
    if entry:
        enabled = not entry.bot_enabled
        reg.set_bot_enabled(registry_id, enabled)
        reg.record_owner_action(
            int(session["user_id"]),
            "enabled" if enabled else "disabled",
            entry,
            "Owner Panel toggle",
        )
        flash(f"{'Enabled' if not entry.bot_enabled else 'Disabled'} the bot for {entry.guild_name}.", "success")
    return redirect(url_for("owner_servers_page"))


@app.route("/owner/servers/<int:registry_id>/remove", methods=["POST"])
@super_admin_required
def owner_remove_server(registry_id):
    entries = reg.list_all()
    entry = next((e for e in entries if e.id == registry_id), None)
    if entry is None:
        flash("Server record not found.", "error")
        return redirect(url_for("owner_servers_page"))

    if not leave_discord_guild(entry.guild_id):
        flash(f"Could not remove the bot from {entry.guild_name}; the server record was kept.", "error")
        return redirect(url_for("owner_servers_page"))

    reg.record_owner_action(int(session["user_id"]), "removed", entry, "Bot removed from Discord server")
    reg.remove(registry_id)
    flash(f"Removed {entry.guild_name}. The bot must be approved again before it can rejoin.", "success")
    return redirect(url_for("owner_servers_page"))


@app.route("/owner/servers/<int:registry_id>/resend-invite", methods=["POST"])
@super_admin_required
def owner_resend_invite(registry_id):
    entry = next((server for server in reg.list_all() if server.id == registry_id), None)
    if entry is None:
        flash("Server record not found.", "error")
        return redirect(url_for("owner_servers_page"))
    invite_url = bot_invite_url()
    dm_text = (
        f"✅ Access for **{entry.guild_name}** is approved. Add the bot again with this link:\n"
        f"{invite_url or 'The bot invite link is not configured; please contact an administrator.'}"
    )
    if not send_discord_dm(entry.owner_discord_id, dm_text):
        flash("The invite could not be sent. Check the bot token and the owner's DM settings.", "error")
        return redirect(url_for("owner_server_detail", registry_id=registry_id))
    reg.record_owner_action(int(session["user_id"]), "invite_resent", entry, "Approval invite sent")
    flash(f"Invite sent to {entry.owner_discord_name}.", "success")
    return redirect(url_for("owner_server_detail", registry_id=registry_id))


@app.route("/owner/servers/<int:registry_id>/review", methods=["POST"])
@super_admin_required
def owner_start_review(registry_id):
    entry = reg.start_review(registry_id, int(session["user_id"]))
    if entry:
        reg.record_owner_action(int(session["user_id"]), "review_started", entry, "Server marked under review")
        flash(f"{entry.guild_name} is now under review.", "success")
    else:
        flash("Server record not found.", "error")
    return redirect(url_for("owner_server_detail", registry_id=registry_id))


@app.route("/owner/servers/<int:registry_id>/status", methods=["POST"])
@super_admin_required
def owner_change_status(registry_id):
    status = request.form.get("status", "")
    entry = reg.set_status(registry_id, status, int(session["user_id"]))
    if entry:
        reg.record_owner_action(int(session["user_id"]), f"status_{status}", entry, "Owner Panel status change")
        flash(f"{entry.guild_name} status changed to {status.replace('_', ' ')}.", "success")
    else:
        flash("Server record not found.", "error")
    return redirect(url_for("owner_server_detail", registry_id=registry_id))


@app.route("/owner/servers/<int:registry_id>/note", methods=["POST"])
@super_admin_required
def owner_update_note(registry_id):
    entry = reg.update_note(registry_id, request.form.get("note", "").strip() or None)
    if entry:
        reg.record_owner_action(int(session["user_id"]), "note_updated", entry, entry.note or "Note cleared")
        flash("Review notes saved.", "success")
    else:
        flash("Server record not found.", "error")
    return redirect(url_for("owner_server_detail", registry_id=registry_id))


@app.route("/owner/servers/<int:registry_id>/regenerate-invite", methods=["POST"])
@super_admin_required
def owner_regenerate_invite(registry_id):
    entry = next((server for server in reg.list_all() if server.id == registry_id), None)
    if entry is None:
        flash("Server record not found.", "error")
        return redirect(url_for("owner_servers_page"))
    invite_url, error = create_review_invite(entry.guild_id)
    if not invite_url:
        reg.set_invite_error(registry_id, error or "Invite creation failed")
        flash(f"Could not create invite: {error}", "error")
        return redirect(url_for("owner_server_detail", registry_id=registry_id))
    reg.set_invite(registry_id, invite_url, REVIEW_INVITE_MAX_AGE)
    reg.record_owner_action(int(session["user_id"]), "invite_regenerated", entry, "Review invite regenerated")
    flash("Review invite regenerated.", "success")
    return redirect(url_for("owner_server_detail", registry_id=registry_id))


@app.route("/owner/servers/<int:registry_id>/revoke-invite", methods=["POST"])
@super_admin_required
def owner_revoke_invite(registry_id):
    entry = next((server for server in reg.list_all() if server.id == registry_id), None)
    if entry is None:
        flash("Server record not found.", "error")
        return redirect(url_for("owner_servers_page"))
    code = invite_code(entry.invite_url)
    if not code:
        flash("No stored invite to revoke.", "error")
        return redirect(url_for("owner_server_detail", registry_id=registry_id))
    response = requests.delete(
        f"https://discord.com/api/v10/invites/{code}",
        headers=bot_api_headers(),
        timeout=10,
    )
    if response.status_code not in (200, 204, 404):
        flash(f"Could not revoke invite ({response.status_code}).", "error")
        return redirect(url_for("owner_server_detail", registry_id=registry_id))
    reg.clear_invite(registry_id)
    reg.record_owner_action(int(session["user_id"]), "invite_revoked", entry, "Review invite revoked")
    flash("Review invite revoked.", "success")
    return redirect(url_for("owner_server_detail", registry_id=registry_id))


# ---------- server config ----------

SERVER_CONFIG_DEFAULTS = {
    "welcome_channel_id": None,
    "welcome_message": "Welcome {mention} to {server}!",
    "leave_channel_id": None,
    "leave_message": "{user} has left {server}.",
    "auto_role_id": None,
    "log_channel_id": None,
}


@app.route("/server-config", methods=["GET", "POST"])
@login_required
def server_config_page():
    config = load_json(selected_guild_file("server_config.json"), dict(SERVER_CONFIG_DEFAULTS))
    for key, default in SERVER_CONFIG_DEFAULTS.items():
        config.setdefault(key, default)

    if request.method == "POST":
        new_config = {
            "welcome_channel_id": request.form.get("welcome_channel_id") or None,
            "welcome_message": request.form.get("welcome_message", "").strip(),
            "leave_channel_id": request.form.get("leave_channel_id") or None,
            "leave_message": request.form.get("leave_message", "").strip(),
            "auto_role_id": request.form.get("auto_role_id") or None,
            "log_channel_id": request.form.get("log_channel_id") or None,
        }
        save_json(selected_guild_file("server_config.json"), new_config)
        flash("Saved - takes effect immediately, no restart needed.", "success")
        return redirect(url_for("server_config_page"))

    return render_template(
        "server_config.html",
        username=session.get("username"),
        active_tab="server_config",
        config=config,
        channels=fetch_guild_channels(),
        roles=fetch_guild_roles(),
    )


# ---------- logs ----------

@app.route("/logs")
@login_required
def logs_page():
    logs = load_json(BOT_LOGS_FILE, [])
    logs = list(reversed(logs))[:150]
    for entry in logs:
        entry["time_display"] = datetime.fromtimestamp(entry["time"]).strftime("%b %d, %H:%M:%S")
    return render_template(
        "logs.html",
        username=session.get("username"),
        active_tab="logs",
        logs=logs,
    )


# ---------- embed builder ----------

def load_webhooks() -> list[dict]:
    return load_json(WEBHOOKS_FILE, [])


def save_webhooks(webhooks: list[dict]):
    save_json(WEBHOOKS_FILE, webhooks)


@app.route("/embed-builder")
@login_required
def embed_builder_page():
    return render_template(
        "embed_builder.html",
        username=session.get("username"),
        active_tab="embed_builder",
        webhooks=load_webhooks(),
    )


@app.route("/embed-builder/webhooks", methods=["POST"])
@login_required
def embed_builder_add_webhook():
    webhooks = load_webhooks()
    name = request.form.get("name", "").strip()
    url = request.form.get("url", "").strip()
    if name and url:
        webhooks.append({"name": name, "url": url})
        save_webhooks(webhooks)
        flash("Webhook saved.", "success")
    return redirect(url_for("embed_builder_page"))


@app.route("/embed-builder/webhooks/<int:index>/delete", methods=["POST"])
@login_required
def embed_builder_delete_webhook(index):
    webhooks = load_webhooks()
    if 0 <= index < len(webhooks):
        webhooks.pop(index)
        save_webhooks(webhooks)
        flash("Webhook removed.", "success")
    return redirect(url_for("embed_builder_page"))


@app.route("/embed-builder/send", methods=["POST"])
@login_required
def embed_builder_send():
    webhook_url = request.form.get("webhook_url", "").strip()
    payload_raw = request.form.get("payload", "").strip()

    if not webhook_url or not payload_raw:
        return {"ok": False, "error": "Missing webhook URL or payload."}, 400

    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Invalid JSON: {e}"}, 400

    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        if resp.status_code >= 300:
            return {"ok": False, "error": f"Discord returned {resp.status_code}: {resp.text[:300]}"}, 400
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500


# ---------- partners ----------

def load_partners() -> dict:
    return load_json(selected_guild_file("partner_data.json"), {"partners": [], "channel_id": None, "message_id": None})


def save_partners(data: dict):
    save_json(selected_guild_file("partner_data.json"), data)


@app.route("/partners")
@login_required
def partners_page():
    data = load_partners()
    partners = [{**p, "id": i} for i, p in enumerate(data["partners"])]
    return render_template(
        "partners.html",
        username=session.get("username"),
        active_tab="partners",
        partners=partners,
    )


@app.route("/partners/add", methods=["POST"])
@login_required
def partners_add():
    data = load_partners()
    data["partners"].append({
        "name": request.form["name"].strip(),
        "link": request.form["link"].strip(),
        "note": request.form.get("note", "").strip(),
    })
    save_partners(data)
    flash("Partner added.", "success")
    return redirect(url_for("partners_page"))


@app.route("/partners/<int:partner_id>/remove", methods=["POST"])
@login_required
def partners_remove(partner_id):
    data = load_partners()
    if 0 <= partner_id < len(data["partners"]):
        data["partners"].pop(partner_id)
        save_partners(data)
        flash("Partner removed.", "success")
    return redirect(url_for("partners_page"))


# ---------- maintenance mode ----------

@app.route("/maintenance", methods=["GET", "POST"])
@login_required
def maintenance_page():
    config = load_json(selected_guild_file("maintenance.json"), {"enabled": False, "allowed_user_id": None})

    if request.method == "POST":
        enabled = "enabled" in request.form
        allowed_user_id = request.form.get("allowed_user_id", "").strip() or session.get("user_id")
        save_json(selected_guild_file("maintenance.json"), {"enabled": enabled, "allowed_user_id": allowed_user_id})
        flash(
            "Maintenance mode ON - every command is now blocked for everyone except the exempt user." if enabled
            else "Maintenance mode OFF - normal permissions restored.",
            "success" if not enabled else "error",
        )
        return redirect(url_for("maintenance_page"))

    return render_template(
        "maintenance.html",
        username=session.get("username"),
        active_tab="maintenance",
        config=config,
        my_user_id=session.get("user_id"),
    )


# ---------- bot control ----------

def get_service_status(service: str) -> dict:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service], capture_output=True, text=True, timeout=5
        )
        active = result.stdout.strip() == "active"
    except Exception:
        active = None  # unknown - couldn't check

    uptime = None
    try:
        result = subprocess.run(
            ["systemctl", "show", service, "--property=ActiveEnterTimestamp", "--value"],
            capture_output=True, text=True, timeout=5,
        )
        ts = result.stdout.strip()
        if ts:
            uptime = ts
    except Exception:
        pass

    return {"active": active, "since": uptime}


@app.route("/control")
@super_admin_required
def control_page():
    bot_status = get_service_status("swbot")
    dashboard_status = get_service_status("swbot-dashboard")
    return render_template(
        "control.html",
        username=session.get("username"),
        active_tab="owner_control",
        bot_status=bot_status,
        dashboard_status=dashboard_status,
    )


@app.route("/control/restart/<service>", methods=["POST"])
@super_admin_required
def restart_service(service):
    allowed_services = {"swbot", "swbot-dashboard"}
    if service not in allowed_services:
        flash("Unknown service.", "error")
        return redirect(url_for("control_page"))

    try:
        subprocess.run(["sudo", "/usr/bin/systemctl", "restart", service], check=True, timeout=15)
        flash(f"Restarted {service}.", "success")
    except Exception as e:
        flash(f"Failed to restart {service}: {e}", "error")

    return redirect(url_for("control_page"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)