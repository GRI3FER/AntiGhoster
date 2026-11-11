import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE = os.environ.get("ALUMNI_TRACKER_DATABASE", str(BASE_DIR / "alumni_tracker.sqlite3"))
VERIFICATION_SECRET = os.environ.get("ALUMNI_TRACKER_VERIFICATION_SECRET", "development-only-secret")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("ALUMNI_TRACKER_SESSION_SECRET", "development-only-session-secret")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('student', 'alumni')),
            email_verified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS email_verifications (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS networks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            join_mode TEXT NOT NULL CHECK (join_mode IN ('open', 'password', 'application')),
            password_hash TEXT
        );
        CREATE TABLE IF NOT EXISTS memberships (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            network_id INTEGER NOT NULL REFERENCES networks(id) ON DELETE CASCADE,
            status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'rejected', 'evidence_requested')),
            participation_years TEXT,
            supporting_information TEXT,
            review_note TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, network_id)
        );
        CREATE TABLE IF NOT EXISTS managers (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            network_id INTEGER NOT NULL REFERENCES networks(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, network_id)
        );
        """
    )
    db.commit()


def json_error(message, status=400):
    return jsonify({"error": message}), status


def request_data():
    return request.get_json(silent=True) or {}


def valid_edu_email(email):
    if not isinstance(email, str) or email.count("@") != 1:
        return False
    local, domain = email.rsplit("@", 1)
    return bool(local and domain.lower().endswith(".edu") and domain.lower() != ".edu")


def valid_email(email):
    if not isinstance(email, str) or email.count("@") != 1:
        return False
    local, domain = email.rsplit("@", 1)
    return bool(local and domain and "." in domain and not domain.startswith("."))


def email_token(user_id, raw_token):
    digest = hmac.new(
        VERIFICATION_SECRET.encode(), f"{user_id}:{raw_token}".encode(), hashlib.sha256
    ).hexdigest()
    return digest


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return json_error("Authentication required", 401)
        g.user = user
        return view(*args, **kwargs)

    return wrapped


def verified_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not g.user["email_verified"]:
            return json_error("Verify your email before accessing the network", 403)
        return view(*args, **kwargs)

    return wrapped


def network_for(network_id):
    return get_db().execute("SELECT * FROM networks WHERE id = ?", (network_id,)).fetchone()


def membership_for(user_id, network_id):
    return get_db().execute(
        "SELECT * FROM memberships WHERE user_id = ? AND network_id = ?", (user_id, network_id)
    ).fetchone()


def alumni_access_allowed(user, membership):
    return (
        user["email_verified"]
        and membership is not None
        and membership["status"] == "active"
    )


@app.route("/api/register", methods=["POST"])
def register():
    data = request_data()
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password")
    role = data.get("role")
    if role not in {"student", "alumni"} or not isinstance(password, str) or len(password) < 8:
        return json_error("role must be student or alumni and password must be at least 8 characters")
    if role == "student" and not valid_edu_email(email):
        return json_error("Student accounts require an email domain ending in .edu")
    if not valid_email(email):
        return json_error("A valid email address is required")
    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (email, generate_password_hash(password), role, utc_now()),
        )
    except sqlite3.IntegrityError:
        return json_error("An account with that email already exists", 409)
    user_id = cursor.lastrowid
    raw_token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO email_verifications (user_id, token_hash, created_at) VALUES (?, ?, ?)",
        (user_id, email_token(user_id, raw_token), utc_now()),
    )
    db.commit()
    response = {"user_id": user_id, "message": "Verify your email before accessing the network"}
    if app.config["TESTING"] or app.config["ENV"] == "development":
        response["verification_token"] = raw_token
    return jsonify(response), 201


@app.route("/api/verify-email", methods=["POST"])
def verify_email():
    data = request_data()
    user_id = data.get("user_id")
    raw_token = data.get("token", "")
    row = get_db().execute(
        "SELECT * FROM email_verifications WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is None or not hmac.compare_digest(row["token_hash"], email_token(user_id, raw_token)):
        return json_error("Invalid email verification token", 400)
    db = get_db()
    db.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user_id,))
    db.execute("DELETE FROM email_verifications WHERE user_id = ?", (user_id,))
    db.commit()
    return jsonify({"message": "Email verified"})


@app.route("/api/login", methods=["POST"])
def login():
    data = request_data()
    user = get_db().execute("SELECT * FROM users WHERE email = ?", (str(data.get("email", "")).lower(),)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], data.get("password", "")):
        return json_error("Invalid email or password", 401)
    if not user["email_verified"]:
        return json_error("Verify your email before logging in", 403)
    session["user_id"] = user["id"]
    return jsonify({"message": "Logged in", "user_id": user["id"]})


@app.route("/api/networks", methods=["POST"])
@verified_required
def create_network():
    data = request_data()
    name = str(data.get("name", "")).strip()
    join_mode = data.get("join_mode")
    if not name or join_mode not in {"open", "password", "application"}:
        return json_error("name and a valid join_mode are required")
    password = data.get("password")
    if join_mode == "password" and (not isinstance(password, str) or not password):
        return json_error("Password-protected networks require a password")
    db = get_db()
    cursor = db.execute(
        "INSERT INTO networks (name, join_mode, password_hash) VALUES (?, ?, ?)",
        (name, join_mode, generate_password_hash(password) if password else None),
    )
    network_id = cursor.lastrowid
    db.execute("INSERT INTO managers (user_id, network_id) VALUES (?, ?)", (g.user["id"], network_id))
    db.commit()
    return jsonify({"network_id": network_id}), 201


@app.route("/api/networks/<int:network_id>/join", methods=["POST"])
@verified_required
def join_network(network_id):
    network = network_for(network_id)
    if network is None:
        return json_error("Network not found", 404)
    data = request_data()
    if network["join_mode"] == "password" and not check_password_hash(
        network["password_hash"], data.get("password", "")
    ):
        return json_error("Incorrect network password", 403)
    if membership_for(g.user["id"], network_id):
        return json_error("Membership already exists", 409)
    is_alumni = g.user["role"] == "alumni"
    if is_alumni and (
        not isinstance(data.get("participation_years"), str)
        or not data["participation_years"].strip()
        or not isinstance(data.get("supporting_information"), str)
        or not data["supporting_information"].strip()
    ):
        return json_error(
            "Alumni applications require participation years and supporting information"
        )
    status = "pending" if is_alumni or network["join_mode"] == "application" else "active"
    db = get_db()
    db.execute(
        """INSERT INTO memberships
           (user_id, network_id, status, participation_years, supporting_information, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (g.user["id"], network_id, status, data.get("participation_years"),
         data.get("supporting_information"), utc_now()),
    )
    db.commit()
    return jsonify({"status": status, "message": "Manager approval is required" if is_alumni else "Joined"}), 201


@app.route("/api/networks/<int:network_id>/application", methods=["GET"])
@login_required
def application_preview(network_id):
    membership = membership_for(g.user["id"], network_id)
    if membership is None:
        return json_error("Application not found", 404)
    return jsonify(
        {
            "status": membership["status"],
            "participation_years": membership["participation_years"],
            "supporting_information": membership["supporting_information"],
            "review_note": membership["review_note"],
            "limited_preview": membership["status"] != "active",
        }
    )


@app.route("/api/networks/<int:network_id>/members", methods=["GET"])
@login_required
def members(network_id):
    membership = membership_for(g.user["id"], network_id)
    if not alumni_access_allowed(g.user, membership):
        return json_error("Network access is pending manager approval", 403)
    rows = get_db().execute(
        """SELECT u.id, u.email, u.role FROM users u
           JOIN memberships m ON m.user_id = u.id
           WHERE m.network_id = ? AND m.status = 'active'""",
        (network_id,),
    ).fetchall()
    return jsonify({"members": [dict(row) for row in rows]})


@app.route("/api/networks/<int:network_id>/members/<int:user_id>/review", methods=["POST"])
@login_required
def review_membership(network_id, user_id):
    manager = get_db().execute(
        "SELECT 1 FROM managers WHERE user_id = ? AND network_id = ?", (g.user["id"], network_id)
    ).fetchone()
    if manager is None:
        return json_error("Only a manager of this network can review applications", 403)
    decision = request_data().get("decision")
    if decision not in {"approve", "reject", "request_evidence"}:
        return json_error("decision must be approve, reject, or request_evidence")
    membership = membership_for(user_id, network_id)
    if membership is None:
        return json_error("Membership not found", 404)
    status = {"approve": "active", "reject": "rejected", "request_evidence": "evidence_requested"}[decision]
    get_db().execute(
        "UPDATE memberships SET status = ?, review_note = ? WHERE user_id = ? AND network_id = ?",
        (status, request_data().get("note"), user_id, network_id),
    )
    get_db().commit()
    return jsonify({"status": status})


@app.route("/api/me/role", methods=["POST"])
@login_required
def change_role():
    new_role = request_data().get("role")
    if new_role not in {"student", "alumni"}:
        return json_error("role must be student or alumni")
    if new_role == "student" and (
        not g.user["email_verified"] or not valid_edu_email(g.user["email"])
    ):
        return json_error("Student status requires a verified .edu address", 403)
    db = get_db()
    db.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, g.user["id"]))
    if new_role == "alumni":
        db.execute(
            """UPDATE memberships SET status = 'pending', review_note = 'Alumni status requires manager review'
               WHERE user_id = ? AND status = 'active'""",
            (g.user["id"],),
        )
    db.commit()
    return jsonify({"role": new_role})


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True)
