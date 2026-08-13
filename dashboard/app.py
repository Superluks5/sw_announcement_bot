"""
Bot Dashboard - Phase 1
------------------------
A small local web app for editing permissions_config.json through a form
instead of nano/scp. Runs bound to 127.0.0.1 only (not exposed to the
internet) - access it through an SSH tunnel, see README notes below.

Login is a single shared password stored in .env, not a full user system -
fine for a single-admin (or small trusted leadership) setup. Can be
extended later with real accounts if needed.
"""

import os
import json
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY", "change-me-in-env")

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD")

# Shared with the bot - same file, same folder structure
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERMISSIONS_FILE = os.path.join(BASE_DIR, "permissions_config.json")


def load_permissions() -> dict:
    if not os.path.exists(PERMISSIONS_FILE):
        return {}
    with open(PERMISSIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_permissions(data: dict):
    with open(PERMISSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not DASHBOARD_PASSWORD:
            flash("DASHBOARD_PASSWORD isn't set in .env yet - the dashboard is locked out until it is.", "error")
        elif request.form.get("password") == DASHBOARD_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("permissions_page"))
        else:
            flash("Wrong password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return redirect(url_for("permissions_page"))


@app.route("/permissions", methods=["GET", "POST"])
@login_required
def permissions_page():
    data = load_permissions()

    if request.method == "POST":
        new_data = {}
        commands = request.form.getlist("command_name")
        role_lists = request.form.getlist("role_ids")

        for command, roles_raw in zip(commands, role_lists):
            command = command.strip()
            if not command:
                continue
            role_ids = [r.strip() for r in roles_raw.split(",") if r.strip()]
            new_data[command] = role_ids

        save_permissions(new_data)
        flash("Saved. Restart the bot for changes to take effect (sudo systemctl restart swbot).", "success")
        return redirect(url_for("permissions_page"))

    # Sort alphabetically so the list is stable and easy to scan
    sorted_items = sorted(data.items())
    return render_template("permissions.html", items=sorted_items)


if __name__ == "__main__":
    # Bound to localhost only - not reachable from outside the VM directly.
    # Access it via an SSH tunnel (see the setup notes you were given).
    app.run(host="127.0.0.1", port=5000, debug=False)
