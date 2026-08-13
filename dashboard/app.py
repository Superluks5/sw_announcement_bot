"""
Bot Dashboard
------------------------
Public landing page -> Discord OAuth login (allowlisted user IDs) ->
dashboard home (usage analytics + module cards) -> per-module pages.
"""

import os
import json
import time
from datetime import datetime
from functools import wraps
from urllib.parse import urlencode

import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY", "change-me-in-env")

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = os.environ.get("GUILD_ID", "1535372103593894028")
BOT_NAME = os.environ.get("BOT_NAME", "Imperial Command System")

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "http://localhost:5000/callback")

ALLOWED_USER_IDS = {
    uid.strip() for uid in os.environ.get("DASHBOARD_ALLOWED_USER_IDS", "").split(",") if uid.strip()
}

PERMISSIONS_FILE = os.path.join(BASE_DIR, "permissions_config.json")
TOGGLES_FILE = os.path.join(BASE_DIR, "command_toggles.json")
USAGE_FILE = os.path.join(BASE_DIR, "usage_data.json")
ROADMAP_FILE = os.path.join(BASE_DIR, "roadmap_data.json")

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
            f"https://discord.com/api/v10/guilds/{GUILD_ID}/roles",
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
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# ---------- public landing ----------

@app.route("/")
def landing():
    return render_template("landing.html", bot_name=BOT_NAME)


# ---------- auth ----------

@app.route("/login")
def login():
    if not DISCORD_CLIENT_ID:
        return "DISCORD_CLIENT_ID isn't set in .env yet - see setup notes.", 500
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
    }
    auth_url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"
    return render_template("login.html", auth_url=auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        flash("Login was cancelled or failed.", "error")
        return redirect(url_for("login"))

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

    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        flash("Your Discord account isn't authorized for this dashboard.", "error")
        return redirect(url_for("login"))

    session["user_id"] = user_id
    session["username"] = user.get("username", "Unknown")
    return redirect(url_for("dashboard_home"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


# ---------- dashboard home ----------

@app.route("/dashboard")
@login_required
def dashboard_home():
    usage = load_json(USAGE_FILE, {})
    sorted_usage = sorted(usage.items(), key=lambda kv: kv[1]["count"], reverse=True)[:10]

    top_commands = []
    for cmd, stats in sorted_usage:
        last_used_display = "-"
        if stats.get("last_used"):
            last_used_display = datetime.fromtimestamp(stats["last_used"]).strftime("%b %d, %H:%M")
        top_commands.append((cmd, {**stats, "last_used_display": last_used_display}))

    return render_template(
        "dashboard_home.html",
        username=session.get("username"),
        active_tab="home",
        top_commands=top_commands,
    )


# ---------- permissions ----------

@app.route("/permissions", methods=["GET", "POST"])
@login_required
def permissions_page():
    data = load_json(PERMISSIONS_FILE, {})
    toggles = load_json(TOGGLES_FILE, {})
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

        save_json(PERMISSIONS_FILE, new_data)
        save_json(TOGGLES_FILE, new_toggles)
        flash("Saved. Restart the bot for changes to take effect (sudo systemctl restart swbot).", "success")
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
    return load_json(ROADMAP_FILE, {"items": [], "channel_id": None, "message_id": None})


def save_roadmap(data: dict):
    save_json(ROADMAP_FILE, data)


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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)