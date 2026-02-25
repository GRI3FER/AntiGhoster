"""
Run this once to get your Beeper access token.
It will save it to .env automatically.

Usage: python get_token.py
"""

import base64
import hashlib
import os
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

BASE_URL = "http://localhost:23373"
REDIRECT_URI = "http://localhost:9876/callback"
PORT = 9876

# PKCE helpers
def pkce_pair():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge



def register_client():
    resp = requests.post(f"{BASE_URL}/oauth/register", json={
        "client_name": "AntiGhoster",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    })
    resp.raise_for_status()
    return resp.json()


# Step 2 — open browser to authorize
def get_auth_url(client_id, state, code_challenge):
    params = urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    return f"{BASE_URL}/oauth/authorize?{params}"


# Step 3 — exchange code for token
def exchange_code(code, client_id, code_verifier):
    resp = requests.post(f"{BASE_URL}/oauth/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": code_verifier,
    })
    resp.raise_for_status()
    return resp.json()


# Step 4 — save to .env
def save_token(token):
    env_path = os.path.join(os.path.dirname(__file__), ".env")

    # Read existing lines (if any)
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()

    # Replace or append BEEPER_ACCESS_TOKEN
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("BEEPER_ACCESS_TOKEN="):
            lines[i] = f"BEEPER_ACCESS_TOKEN={token}\n"
            updated = True
            break
    if not updated:
        lines.append(f"BEEPER_ACCESS_TOKEN={token}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)

    print(f"\n✅ Token saved to .env")


# Local callback server to capture the auth code
auth_code_result = {}

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            auth_code_result["code"] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family:sans-serif;padding:40px;background:#0c0c0e;color:#e8e8f0">
                <h2>&#x2705; Authorized!</h2>
                <p>You can close this tab and go back to the terminal.</p>
                </body></html>
            """)
        else:
            self.send_response(400)
            self.end_headers()
            auth_code_result["error"] = params.get("error", ["unknown"])[0]

    def log_message(self, *args):
        pass  # suppress request logs


def run():
    print("🔐 AntiGhoster — one-time token setup\n")

    # Register client
    print("1. Registering OAuth client with Beeper...")
    try:
        client = register_client()
    except Exception as e:
        print(f"\n❌ Could not reach Beeper Desktop API: {e}")
        print("   Make sure Beeper Desktop is running and the API is enabled.")
        return

    client_id = client["client_id"]
    state = secrets.token_urlsafe(16)
    code_verifier, code_challenge = pkce_pair()
    auth_url = get_auth_url(client_id, state, code_challenge)

    # Start local callback server
    server = HTTPServer(("localhost", PORT), CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.daemon = True
    thread.start()

    # Open browser
    print("2. Opening Beeper in your browser to approve access...")
    print(f"   (If it doesn't open, visit: {auth_url})\n")
    webbrowser.open(auth_url)

    # Wait for callback
    thread.join(timeout=120)

    if "error" in auth_code_result:
        print(f"\n❌ Authorization failed: {auth_code_result['error']}")
        return

    if "code" not in auth_code_result:
        print("\n❌ Timed out waiting for authorization.")
        return

    # Exchange code for token
    print("3. Exchanging code for access token...")
    try:
        token_data = exchange_code(auth_code_result["code"], client_id, code_verifier)
    except Exception as e:
        print(f"\n❌ Token exchange failed: {e}")
        return

    access_token = token_data.get("access_token")
    if not access_token:
        print(f"\n❌ No access token in response: {token_data}")
        return

    save_token(access_token)
    print("\n🟢 All done! Now run: python app.py")


if __name__ == "__main__":
    run()