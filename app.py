import os
import json
import urllib.parse
import mimetypes
import requests
import time as _time
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify, request, Response
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

BASE_URL     = os.getenv("BEEPER_BASE_URL", "http://localhost:23373")
ACCESS_TOKEN = os.getenv("BEEPER_ACCESS_TOKEN", "")

SETTINGS_FILE = Path(__file__).parent / "settings.json"
DEFAULT_SETTINGS = {
    "setup_complete": False,
    "people":         [],  # [{id, display_name, chat_ids}]
}

# In-memory cache — busted on manual refresh
_chat_cache = {"ts": 0, "data": None}
CACHE_TTL   = 90  # seconds

def get_cached_chats():
    if _chat_cache["data"] and (_time.time() - _chat_cache["ts"]) < CACHE_TTL:
        return _chat_cache["data"]
    chats = fetch_all_chats()
    _chat_cache["ts"]   = _time.time()
    _chat_cache["data"] = chats
    return chats

def load_settings():
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    return DEFAULT_SETTINGS.copy()

def save_settings(s):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)

def beeper_get(path, params=None):
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"} if ACCESS_TOKEN else {}
    try:
        r = requests.get(f"{BASE_URL}{path}", headers=headers, params=params, timeout=30)
    except requests.exceptions.ConnectionError:
        raise Exception("Cannot reach Beeper Desktop. Make sure it's running with the API enabled.")
    if r.status_code == 401:
        raise Exception("Unauthorized — check BEEPER_ACCESS_TOKEN in .env")
    r.raise_for_status()
    return r.json()

def fetch_all_chats():
    chats  = []
    params = {"limit": 50, "includeMuted": "true", "includeArchived": "true"}
    while True:
        data  = beeper_get("/v1/chats", params=params)
        items = data.get("items", [])
        chats.extend(items)
        if not data.get("hasMore") or not data.get("oldestCursor"):
            break
        params = {**params, "cursor": data["oldestCursor"]}
    return chats

def parse_timestamp(ts):
    if ts is None: return None
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts, tz=timezone.utc)
    if isinstance(ts, str):
        try: return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except: return None
    return None

def extract_network(account_id):
    a = (account_id or "").lower()
    for kw, name in [
        ("instagram","Instagram"),("whatsapp","WhatsApp"),("telegram","Telegram"),
        ("signal","Signal"),("imessage","iMessage"),("apple","iMessage"),
        ("messenger","Messenger"),("facebook","Messenger"),("discord","Discord"),
        ("slack","Slack"),("linkedin","LinkedIn"),("twitter","X"),("x.com","X"),
        ("googlemessages","Google Messages"),("rcs","Google Messages"),
    ]:
        if kw in a: return name
    return "Other"

def parse_chat_simple(chat, is_group=False):
    preview    = chat.get("preview") or {}
    account_id = chat.get("accountID") or chat.get("account_id") or ""
    network    = extract_network(account_id)
    parts      = chat.get("participants", {}).get("items", [])
    other      = [p for p in parts if not p.get("isSelf") and not p.get("is_self")]
    name       = chat.get("name") or chat.get("title")
    avatar     = chat.get("avatar")
    handle     = None

    if not is_group and other:
        name   = name or other[0].get("fullName") or other[0].get("name") or other[0].get("displayName")
        avatar = avatar or other[0].get("imgURL") or other[0].get("avatar")
        handle = other[0].get("username") or other[0].get("handle") or other[0].get("phoneNumber")

    # Use your sent timestamp if you sent last; fall back to lastActivity otherwise
    i_sent = preview.get("isSender", False)
    now    = datetime.now(tz=timezone.utc)
    ts     = parse_timestamp(preview.get("timestamp")) if i_sent else parse_timestamp(chat.get("lastActivity"))
    days_since = (now - ts).days if ts else None

    last_activity_ts   = parse_timestamp(chat.get("lastActivity"))
    last_activity_days = (now - last_activity_ts).days if last_activity_ts else None

    members = []
    if is_group:
        members = [{"name": p.get("fullName") or p.get("name") or p.get("displayName"),
                    "handle": p.get("username") or p.get("handle"),
                    "avatar": p.get("imgURL") or p.get("avatar")} for p in other]

    return {
        "id": chat.get("id"), "name": name or "Unknown",
        "avatar": avatar, "handle": handle, "network": network,
        "last_message_ts": ts.isoformat() if ts else None,
        "days_since": days_since,
        "last_activity_days": last_activity_days,
        "i_sent_last": i_sent,
        "is_group": is_group, "members": members, "member_count": len(other) if is_group else 0,
    }


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())

@app.route("/api/settings", methods=["POST"])
def post_settings():
    s = load_settings()
    s.update(request.json)
    save_settings(s)
    return jsonify({"ok": True})

@app.route("/api/contacts/raw")
def api_contacts_raw():
    try:
        all_chats = get_cached_chats()
        seen = {}
        for c in all_chats:
            cid = c.get("id")
            if cid and cid not in seen:
                seen[cid] = c

        dms, groups = [], []
        for c in seen.values():
            is_group = (c.get("type") or "").lower() == "group"
            parsed   = parse_chat_simple(c, is_group=is_group)
            (groups if is_group else dms).append(parsed)

        dms.sort(key=lambda c: (c["days_since"] is None, c["days_since"] or 0, (c["name"] or "").lower()))
        return jsonify({"contacts": dms, "groups": groups, "total": len(dms) + len(groups)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/people")
def api_people():
    try:
        if request.args.get("bust"):
            _chat_cache["data"] = None
        settings   = load_settings()
        people_cfg = settings.get("people", [])

        if not people_cfg:
            return jsonify({"people": []})

        all_raw    = get_cached_chats()
        chat_index = {c["id"]: c for c in all_raw if c.get("id")}
        result     = []

        for person in people_cfg:
            chat_ids = person.get("chat_ids", [])
            chats    = [parse_chat_simple(chat_index[cid], is_group=(chat_index[cid].get("type") == "group"))
                        for cid in chat_ids if cid in chat_index]

            if not chats:
                result.append({
                    "id": person["id"], "display_name": person["display_name"],
                    "days_since": None, "last_message_ts": None,
                    "networks": [], "avatar": None, "urgency": 0, "waiting_on_you": False,
                    "linked_chats": [],
                })
                continue

            chats_with_ts = [c for c in chats if c["days_since"] is not None]
            freshest      = min(chats_with_ts, key=lambda c: c["days_since"]) if chats_with_ts else None
            days_since    = freshest["days_since"] if freshest else None

            waiting_on_you = (
                freshest is not None and
                not freshest.get("i_sent_last") and
                (freshest.get("last_activity_days") or 999) < 30
            )

            networks = list(dict.fromkeys(c["network"] for c in chats))

            def avatar_priority(c):
                n = c.get("network", "")
                if n == "Instagram": return 0
                if n == "WhatsApp":  return 1
                return 2
            avatar_chat = next((c for c in sorted(chats, key=avatar_priority) if c.get("avatar")), None)
            avatar      = avatar_chat["avatar"] if avatar_chat else None

            if days_since is None:  urgency = 3 if waiting_on_you else 0
            elif days_since <= 1:   urgency = 5
            elif days_since <= 7:   urgency = 4
            elif days_since <= 13:  urgency = 3
            elif days_since <= 30:  urgency = 2
            elif days_since <= 90:  urgency = 1
            else:                   urgency = 0

            result.append({
                "id":              person["id"],
                "display_name":    person["display_name"],
                "days_since":      days_since,
                "last_message_ts": freshest["last_message_ts"] if freshest else None,
                "networks":        networks,
                "avatar":          avatar,
                "urgency":         urgency,
                "waiting_on_you":  waiting_on_you,
                "linked_chats":    [{"id": c["id"], "name": c["name"], "network": c["network"],
                                     "is_group": c["is_group"], "members": c["members"],
                                     "member_count": c["member_count"]} for c in chats],
            })

        has_ts = sorted([p for p in result if p["days_since"] is not None],
                        key=lambda x: x["days_since"], reverse=True)
        no_ts  = [p for p in result if p["days_since"] is None]
        return jsonify({"people": has_ts + no_ts})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/avatar")
def api_avatar():
    path = request.args.get("path", "")
    if path.startswith("file:///"):
        fpath = urllib.parse.unquote(path[8:])
        try:
            with open(fpath, "rb") as f:
                data = f.read()
            mime = mimetypes.guess_type(fpath)[0] or "image/jpeg"
            return Response(data, mimetype=mime)
        except:
            return "", 404
    if path.startswith("mxc://"):
        mxc = path[6:]
        server, media = mxc.split("/", 1) if "/" in mxc else (mxc, "")
        url = f"http://localhost:23373/_matrix/media/v3/download/{server}/{media}"
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}, timeout=10)
            return Response(r.content, mimetype=r.headers.get("content-type", "image/jpeg"))
        except:
            return "", 404
    return "", 404

@app.route("/api/status")
def api_status():
    try:
        beeper_get("/v1/accounts")
        return jsonify({"connected": True})
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)}), 503

if __name__ == "__main__":
    print("🟢  AntiGhoster → http://localhost:5000")
    app.run(debug=True, port=5000)