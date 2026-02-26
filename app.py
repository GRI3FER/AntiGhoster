import os
import json
import requests
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

BASE_URL     = os.getenv("BEEPER_BASE_URL", "http://localhost:23373")
ACCESS_TOKEN = os.getenv("BEEPER_ACCESS_TOKEN", "")

SETTINGS_FILE = Path(__file__).parent / "settings.json"
DEFAULT_SETTINGS = {
    "setup_complete":  False,
    "people":          [],   # [{id, display_name, chat_ids}]
    "expanded_groups": [],
}

# Simple in-memory cache so we don't re-fetch all chats on every request
import time as _time
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
    """Fetch every chat with no type filter — most efficient, returns everything."""
    chats  = []
    params = {"limit": 50, "includeMuted": "true", "includeArchived": "true"}
    page   = 0
    while True:
        data  = beeper_get("/v1/chats", params=params)
        items = data.get("items", [])
        chats.extend(items)
        page += 1
        if not data.get("hasMore") or not data.get("oldestCursor"):
            break
        params = {**params, "cursor": data["oldestCursor"]}
    return chats

def fetch_chats(chat_type=None):
    """Kept for compatibility — just calls fetch_all_chats and optionally filters."""
    all_chats = fetch_all_chats()
    if not chat_type:
        return all_chats
    return [c for c in all_chats if c.get("type") == chat_type]

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
    preview   = chat.get("preview") or {}
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

    # Determine when YOU last texted in this chat.
    # If your message is the preview (isSender=true), use that timestamp directly.
    # If they replied after you, we don't have your exact sent time from the chat list API,
    # so we use lastActivity as a conservative proxy — it's recent enough to be useful.
    i_sent  = preview.get("isSender", False)
    now     = datetime.now(tz=timezone.utc)
    if i_sent:
        ts = parse_timestamp(preview.get("timestamp"))
    else:
        # They replied — lastActivity reflects the whole conversation.
        # Use it as upper bound; we know you texted *at some point* in this chat.
        ts = parse_timestamp(chat.get("lastActivity"))

    days_since = (now - ts).days if ts else None

    # Also grab the last activity for display reference
    last_activity_ts   = parse_timestamp(chat.get("lastActivity"))
    last_activity_days = (now - last_activity_ts).days if last_activity_ts else None

    preview_text = preview.get("text") or ""
    if len(preview_text) > 60: preview_text = preview_text[:60] + "…"

    members = []
    if is_group:
        members = [{"name": p.get("fullName") or p.get("name") or p.get("displayName"),
                    "handle": p.get("username") or p.get("handle"),
                    "avatar": p.get("imgURL") or p.get("avatar")} for p in other]

    return {
        "id": chat.get("id"), "name": name or "Unknown",
        "avatar": avatar, "handle": handle, "network": network,
        "last_message_ts": ts.isoformat() if ts else None,
        "days_since": days_since,          # days since YOU last texted
        "last_activity_days": last_activity_days,  # days since anyone texted
        "i_sent_last": i_sent,
        "preview": preview_text,
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
            # Only classify as group if explicitly typed — participant count is unreliable
            # across platforms (Instagram especially)
            chat_type = (c.get("type") or "").lower()
            is_group  = chat_type == "group"
            parsed    = parse_chat_simple(c, is_group=is_group)
            (groups if is_group else dms).append(parsed)

        dms.sort(key=lambda c: (c["days_since"] is None, c["days_since"] or 0, (c["name"] or "").lower()))
        return jsonify({"contacts": dms, "groups": groups, "total": len(dms) + len(groups)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/people")
def api_people():
    try:
        if request.args.get("bust"):
            _chat_cache["data"] = None  # force re-fetch
        settings       = load_settings()
        people_cfg     = settings.get("people", [])
        expanded_ids   = set(settings.get("expanded_groups", []))

        if not people_cfg:
            return jsonify({"people": []})

        all_raw    = get_cached_chats()
        chat_index = {c["id"]: c for c in all_raw if c.get("id")}

        result = []
        now    = datetime.now(tz=timezone.utc)

        for person in people_cfg:
            chat_ids = person.get("chat_ids", [])
            chats    = [parse_chat_simple(chat_index[cid], is_group=(chat_index[cid].get("type") == "group")) 
                       for cid in chat_ids if cid in chat_index]

            if not chats:
                result.append({
                    "id": person["id"], "display_name": person["display_name"],
                    "days_since": None, "last_message_ts": None,
                    "networks": [], "preview": "", "avatar": None, "urgency": 0,
                })
                continue

            # days_since = days since YOU last texted across all linked chats.
            # parse_chat_simple sets days_since from your sent timestamp if i_sent_last,
            # or lastActivity as fallback when they replied after you.
            # Take the minimum (most recent) across all linked chats.
            chats_with_ts = [c for c in chats if c["days_since"] is not None]
            freshest      = min(chats_with_ts, key=lambda c: c["days_since"]) if chats_with_ts else None
            days_since    = freshest["days_since"] if freshest else None

            # waiting_on_you: they texted last in the most recent chat
            waiting_on_you = (
                freshest is not None and
                not freshest.get("i_sent_last") and
                (freshest.get("last_activity_days") or 999) < 30
            )

            networks = list(dict.fromkeys(c["network"] for c in chats))
            # Avatar priority: Instagram > WhatsApp > any other
            def avatar_priority(c):
                n = c.get("network","")
                if n == "Instagram": return 0
                if n == "WhatsApp":  return 1
                return 2
            avatar_chat = next((c for c in sorted(chats, key=avatar_priority) if c.get("avatar")), None)
            avatar = avatar_chat["avatar"] if avatar_chat else None
            preview  = freshest["preview"] if freshest else next((c["preview"] for c in chats if c.get("preview")), "")

            if days_since is None:    urgency = 3 if waiting_on_you else 0
            elif days_since <= 1:     urgency = 5
            elif days_since <= 7:     urgency = 4
            elif days_since <= 13:    urgency = 3
            elif days_since <= 30:    urgency = 2
            elif days_since <= 90:    urgency = 1
            else:                     urgency = 0

            result.append({
                "id":              person["id"],
                "display_name":    person["display_name"],
                "days_since":      days_since,
                "last_message_ts": freshest["last_message_ts"] if freshest else None,
                "networks":        networks,
                "preview":         preview,
                "avatar":          avatar,
                "urgency":         urgency,
                "waiting_on_you":  waiting_on_you,
                "linked_chats":    [{"id": c["id"], "name": c["name"], "network": c["network"],
                                     "is_group": c["is_group"], "members": c["members"],
                                     "member_count": c["member_count"]} for c in chats],
            })

        # Sort: neglected first, then no data
        has_ts = sorted([p for p in result if p["days_since"] is not None],
                        key=lambda x: x["days_since"], reverse=True)
        no_ts  = [p for p in result if p["days_since"] is None]
        return jsonify({"people": has_ts + no_ts})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/debug/message")
def api_debug_message():
    """Show raw chat fields to find timestamp and sender info."""
    try:
        all_chats = get_cached_chats()
        samples = []
        for c in all_chats[:5]:
            samples.append({
                "chat_name": c.get("name") or c.get("title"),
                "all_keys": list(c.keys()),
                "full": c,
            })
        return jsonify(samples)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/debug")
def api_debug():
    try:
        # Peek at raw first page to see all response keys and pagination fields
        raw        = beeper_get("/v1/chats", {"limit": 25, "includeMuted": "true"})
        raw_keys   = list(raw.keys())
        cursor_val = {k: raw.get(k) for k in raw_keys if any(x in k.lower() for x in ["cursor", "next", "page", "total", "count"])}

        all_chats = get_cached_chats()
        seen = {c["id"]: c for c in all_chats if c.get("id")}
        results   = {"cached": {"fetched": len(all_chats), "unique": len(seen)}}

        network_counts = {}
        for c in seen.values():
            net = extract_network(c.get("accountID") or c.get("account_id") or "")
            network_counts[net] = network_counts.get(net, 0) + 1

        return jsonify({
            "total_unique":      len(seen),
            "by_fetch_type":     results,
            "by_network":        network_counts,
            "raw_response_keys": raw_keys,
            "pagination_fields": cursor_val,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/avatar")
def api_avatar():
    """Proxy local file:// avatar paths so browser can load them."""
    import urllib.parse, mimetypes
    path = request.args.get("path", "")
    if path.startswith("file:///"):
        path = urllib.parse.unquote(path[8:])
        # Windows: file:///C:/... -> C:/...
        if not path.startswith("/") and len(path) > 1 and path[1] == ":":
            pass  # already correct Windows path
        try:
            with open(path, "rb") as f:
                data = f.read()
            mime = mimetypes.guess_type(path)[0] or "image/jpeg"
            from flask import Response
            return Response(data, mimetype=mime)
        except Exception as e:
            return "", 404
    # mxc:// or https:// — pass through
    if path.startswith("mxc://"):
        mxc = path[6:]
        server, media = mxc.split("/", 1) if "/" in mxc else (mxc, "")
        url = f"http://localhost:23373/_matrix/media/v3/download/{server}/{media}"
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}, timeout=10)
            from flask import Response
            return Response(r.content, mimetype=r.headers.get("content-type","image/jpeg"))
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