#!/usr/bin/env python3
"""Get a Deezer access token through the OAuth flow and store it.

Deezer permits exactly one redirect URL per application, and the login page
must be opened by a human in a browser. The flow is therefore two steps:

    python3 scripts/dz_login.py --url             # 1. show the login link
    python3 scripts/dz_login.py --code '<url>'    # 2. give back the address
                                                  #    the browser landed on

Other modes:
    python3 scripts/dz_login.py --serve   catch the redirect on localhost
    python3 scripts/dz_login.py --check   test the stored token

--serve only works when the application's redirect URL points at localhost or
127.0.0.1, and needs a terminal the user controls, because it opens a browser
and waits. --url plus --code works everywhere and is the default for agents.

The application id, secret and redirect URL come from .env — see .env.example
and the /deezer-login skill for how to register the application.
"""
import json
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dz import CONNECT, PERMS, Deezer, DeezerError, load_env, save_token, UA

PAGE = (b"<!doctype html><meta charset=utf-8><title>deezerlair</title>"
        b"<body style='font:16px/1.5 system-ui;padding:3rem'>"
        b"<h1>Deezer connected.</h1><p>Close this tab and go back to the "
        b"terminal.</p>")


def config():
    """Application credentials, or a clear message on what is missing."""
    env = load_env()
    missing = [k for k in ("DEEZER_APP_ID", "DEEZER_APP_SECRET",
                           "DEEZER_REDIRECT_URI") if not env.get(k)]
    if missing:
        sys.exit(f"missing {', '.join(missing)} in .env — register an "
                 f"application at https://developers.deezer.com/myapps "
                 f"and copy .env.example to .env")
    return env


def auth_url(env, perms=PERMS):
    return CONNECT + "/oauth/auth.php?" + urllib.parse.urlencode({
        "app_id": env["DEEZER_APP_ID"],
        "redirect_uri": env["DEEZER_REDIRECT_URI"],
        "perms": perms})


def extract_code(text):
    """Accept a full redirect URL, a query string, or a bare code."""
    text = text.strip().strip("'\"")
    if "code=" in text:
        query = urllib.parse.urlsplit(text).query or text.lstrip("?")
        found = dict(urllib.parse.parse_qsl(query)).get("code")
        if found:
            return found
    if "error_reason" in text:
        sys.exit("Deezer reported: " + text)
    if "/" in text or "?" in text:
        sys.exit(f"no `code` parameter in {text!r} — copy the whole address "
                 f"the browser landed on after you pressed Allow")
    return text


def exchange(env, code):
    """Trade the one-shot code for an access token."""
    url = CONNECT + "/oauth/access_token.php?" + urllib.parse.urlencode({
        "app_id": env["DEEZER_APP_ID"],
        "secret": env["DEEZER_APP_SECRET"],
        "code": code,
        "output": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace").strip()
    try:                                    # output=json is honoured...
        token = json.loads(body).get("access_token")
    except ValueError:                      # ...but plain form data happens
        token = dict(urllib.parse.parse_qsl(body)).get("access_token")
    if not token:
        sys.exit(f"Deezer refused the code: {body or 'empty response'}\n"
                 f"A code is single-use and expires fast — run --url again.")
    return token


def store(token):
    """Verify the token against the API, then save it and report."""
    client = Deezer(token=token)
    profile = client.get("user/me")
    try:
        perms = (client.get("user/me/permissions") or {}).get("permissions", {})
    except DeezerError:
        perms = {}
    path = save_token(token, profile, perms)
    granted = sorted(k for k, v in perms.items() if v)
    print(f"logged in as {profile.get('name')} (id {profile.get('id')}, "
          f"{profile.get('country')})")
    print(f"token stored in {path}")
    if granted:
        print("permissions: " + ", ".join(granted))
    for needed in ("manage_library", "delete_library"):
        if perms and not perms.get(needed):
            print(f"warning: {needed} was not granted — the write scripts "
                  f"will fail. Re-run the flow and accept every permission.",
                  file=sys.stderr)
    return 0


def serve(env):
    """Run a one-shot local listener on the registered redirect URL."""
    target = urllib.parse.urlsplit(env["DEEZER_REDIRECT_URI"])
    if target.hostname not in ("localhost", "127.0.0.1"):
        sys.exit(f"--serve needs a localhost redirect URL, but the "
                 f"application registers {env['DEEZER_REDIRECT_URI']}. "
                 f"Use --url and --code instead.")
    caught = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.urlsplit(self.path).query
            caught.update(dict(urllib.parse.parse_qsl(query)))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE)

        def log_message(self, *a):
            pass

    url = auth_url(env)
    server = HTTPServer((target.hostname, target.port or 80), Handler)
    print(f"open this and press Allow:\n\n  {url}\n")
    webbrowser.open(url)
    while "code" not in caught and "error_reason" not in caught:
        server.handle_request()
    server.server_close()
    if "code" not in caught:
        sys.exit("Deezer reported: " + caught.get("error_reason", "?"))
    return store(exchange(env, caught["code"]))


def check():
    """Report who the stored token belongs to and what it may do."""
    client = Deezer()
    if not client.token:
        sys.exit("no token stored — run: python3 scripts/dz_login.py --url")
    try:
        profile = client.me()
    except DeezerError as e:
        sys.exit(f"stored token is not usable: {e}")
    perms = (client.get("user/me/permissions") or {}).get("permissions", {})
    print(f"{profile.get('name')} (id {profile.get('id')}, "
          f"{profile.get('country')})")
    print("permissions: " + ", ".join(sorted(k for k, v in perms.items() if v)))
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    mode = argv[0]
    if mode == "--check":
        return check()
    env = config()
    if mode == "--url":
        print(auth_url(env))
        return 0
    if mode == "--serve":
        return serve(env)
    if mode == "--code":
        if len(argv) < 2:
            sys.exit("--code needs the address the browser landed on")
        return store(exchange(env, extract_code(argv[1])))
    sys.exit(f"unknown option {mode!r}\n\n{__doc__}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
