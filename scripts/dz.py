#!/usr/bin/env python3
"""Raw Deezer API access — the public half, plus a door to the private half.

Deezer has two APIs, and this repo uses both:

    api.deezer.com    public, no session, clean JSON. Search, catalogue,
                      charts, editorial, an artist's related artists. This
                      script speaks it.
    gw-light          the gateway the website itself uses, authenticated by
                      the `arl` cookie. Everything about *your* account and
                      every write lives here. `dz_gw.py` speaks it, and
                      `--gw` below reaches it from the command line.

Usage:
    dz.py <path> [key=value ...]                  GET a public resource
    dz.py --all <path> [key=value ...]            follow `next`, merge `data`
    dz.py --fields id,title,artist.name <path>    TSV instead of JSON
    dz.py --gw <method> [key=value ...]           call a gateway method

Examples:
    dz.py search q='artist:"boards of canada" track:"roygbiv"' limit=3
    dz.py --all album/302127/tracks --fields id,title
    dz.py artist/27/related --fields id,name
    dz.py chart/0/tracks limit=20 --fields title,artist.name
    dz.py --gw deezer.getUserData
    dz.py --gw playlist.getSongs PLAYLIST_ID=1234 nb=10 start=0
    dz.py --gw deezer.pageProfile USER_ID=123 tab=playlists nb=5

Gateway values are read as JSON when they parse as JSON, so numbers arrive as
numbers and `songs=[[3135556,0]]` arrives as a list. Everything else is a
string. `-X POST`/`-X DELETE` still work against the public API, but its write
endpoints need an OAuth token that Deezer no longer issues — use `--gw`.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://api.deezer.com"
UA = "deezerlair/0.1 (+https://github.com/api-haus/deezerlair)"

# Deezer permits 50 calls per 5 seconds per application. Stay below it, and
# retry anyway — a parallel process shares the same quota.
WINDOW = 5.0
BURST = 40
RETRIES = 4


class DeezerError(RuntimeError):
    """An error the API reported in the response body, not in the status."""

    def __init__(self, message, code=None, kind=None):
        super().__init__(message)
        self.code = code
        self.kind = kind


def load_env(path=None):
    """Read KEY=VALUE lines from .env. A missing file is not an error."""
    env = {}
    p = Path(path) if path else ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("DEEZER_")})
    return env


def load_token():
    """An OAuth token, if one was supplied.

    Deezer stopped issuing API applications, so nobody can obtain one of these
    any more. It stays supported for whoever registered an application back
    when that was possible; everything else in this repo authenticates through
    `dz_gw.py` instead. Nothing here needs a token to read the catalogue.
    """
    return load_env().get("DEEZER_ACCESS_TOKEN") or None


class Deezer:
    """A paced Deezer API client. Import it, or drive it from the CLI below."""

    def __init__(self, token=None, timeout=30, verbose=False):
        self.token = load_token() if token is None else token
        self.timeout = timeout
        self.verbose = verbose
        self._calls = deque()

    # -- plumbing ---------------------------------------------------------

    def redact(self, text):
        """Remove the access token from anything that goes to a log."""
        return text.replace(self.token, "<token>") if self.token else text

    def _pace(self):
        """Block until the call fits inside the quota window."""
        now = time.monotonic()
        while self._calls and now - self._calls[0] > WINDOW:
            self._calls.popleft()
        if len(self._calls) >= BURST:
            time.sleep(WINDOW - (now - self._calls[0]) + 0.05)
            return self._pace()
        self._calls.append(time.monotonic())

    def request(self, path, method="GET", **params):
        """Call one endpoint and return the decoded body.

        Deezer answers a failed call with HTTP 200 and an `error` object, so
        the status alone never tells you whether the call worked.
        """
        path = path.strip("/")
        if path.startswith(("http://", "https://")):
            parts = urllib.parse.urlsplit(path)
            path = parts.path.strip("/")
            for k, v in urllib.parse.parse_qsl(parts.query):
                params.setdefault(k, v)
            params.pop("access_token", None)
        query = {k: v for k, v in params.items() if v is not None}
        if self.token:
            query["access_token"] = self.token
        url = f"{BASE}/{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        if self.verbose:
            print(f"{method} {self.redact(url)}", file=sys.stderr)

        last = None
        for attempt in range(RETRIES):
            self._pace()
            req = urllib.request.Request(
                url, method=method,
                data=b"" if method in ("POST", "PUT") else None,
                headers={"User-Agent": UA, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    raw = r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code < 500 and e.code != 429:
                    raise DeezerError(
                        f"HTTP {e.code} on {self.redact(url)}", code=e.code)
                last = f"HTTP {e.code}"
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = str(e)
            else:
                body = json.loads(raw) if raw.strip() else None
                err = body.get("error") if isinstance(body, dict) else None
                if err:
                    message = err.get("message", "unknown error")
                    code = err.get("code")
                    # Quota and transient server faults are worth another try.
                    if code == 4 or "quota" in str(message).lower():
                        last = message
                    else:
                        if not self.token and err.get("type") == "OAuthException":
                            message += " — run the /deezer-login skill"
                        raise DeezerError(message, code, err.get("type"))
                else:
                    return body
            time.sleep(2 ** attempt)
        raise DeezerError(f"gave up after {RETRIES} tries: {last}")

    # -- convenience ------------------------------------------------------

    def get(self, path, **params):
        return self.request(path, "GET", **params)

    def post(self, path, **params):
        return self.request(path, "POST", **params)

    def delete(self, path, **params):
        return self.request(path, "DELETE", **params)

    def paginate(self, path, max_items=None, **params):
        """Return every `data` row of a list endpoint, following `next`."""
        params.setdefault("limit", 100)
        index = int(params.pop("index", 0))
        out = []
        while True:
            page = self.request(path, index=index, **params)
            if not isinstance(page, dict) or "data" not in page:
                return page if not out else out
            rows = page["data"]
            out.extend(rows)
            if max_items and len(out) >= max_items:
                return out[:max_items]
            nxt = page.get("next")
            if not nxt or not rows:
                return out
            following = dict(urllib.parse.parse_qsl(
                urllib.parse.urlsplit(nxt).query))
            step = int(following.get("index", index + len(rows)))
            if step <= index:            # a stuck cursor would loop forever
                return out
            index = step

    def me(self):
        """The profile behind an OAuth token, for the rare caller that has one.

        Ask `dz_gw.Gw` who the user is instead — that path works without an
        API application, which nobody can register any more.
        """
        if not self.token:
            raise DeezerError(
                "the public API cannot see an account without an OAuth token; "
                "use dz_gw.Gw() — run the /deezer-login skill to connect")
        return self.get("user/me")


# -- output ---------------------------------------------------------------

def pluck(row, dotted):
    """Read a dotted path such as `artist.name` out of a decoded row."""
    value = row
    for part in dotted.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            value = value[int(part)] if int(part) < len(value) else None
        else:
            return None
    return value


def cell(value):
    """Flatten one value into a tab-safe TSV cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value).replace("\t", " ").replace("\n", " ")


def as_tsv(body, fields, header=True):
    """Project a response into tab-separated lines — far cheaper to read."""
    rows = body
    if isinstance(body, dict):
        rows = body.get("data", [body])
    lines = ["#" + "\t".join(fields)] if header else []
    for row in rows:
        lines.append("\t".join(cell(pluck(row, f)) for f in fields))
    return "\n".join(lines)


def main(argv):
    args, params, method, follow = [], {}, "GET", False
    fields, compact, verbose, token, cap = None, False, False, None, None
    gateway = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-X", "--method"):
            i += 1
            method = argv[i].upper()
        elif a == "--all":
            follow = True
        elif a == "--gw":
            gateway = True
        elif a == "--max":
            i += 1
            cap = int(argv[i])
        elif a == "--fields":
            i += 1
            fields = [f.strip() for f in argv[i].split(",") if f.strip()]
        elif a == "--token":
            i += 1
            token = argv[i]
        elif a in ("-c", "--compact"):
            compact = True
        elif a in ("-v", "--verbose"):
            verbose = True
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        elif "=" in a and not a.startswith("-"):
            k, v = a.split("=", 1)
            params[k] = v
        else:
            args.append(a)
        i += 1
    if not args:
        print(__doc__, file=sys.stderr)
        return 2

    if gateway:
        from dz_gw import Gw, GwError          # only this path needs a session
        payload = {}
        for k, v in params.items():
            try:
                payload[k] = json.loads(v)
            except ValueError:
                payload[k] = v
        try:
            gw = Gw(verbose=verbose)
            body = (gw.paginate(args[0], cap=cap, **payload) if follow
                    else gw.call(args[0], **payload))
        except GwError as e:
            print(f"deezer: {e}", file=sys.stderr)
            return 1
    else:
        client = Deezer(token=token, verbose=verbose)
        try:
            if follow:
                body = client.paginate(args[0], max_items=cap, **params)
            else:
                body = client.request(args[0], method, **params)
        except DeezerError as e:
            code = f" (code {e.code})" if e.code is not None else ""
            print(f"deezer: {e}{code}", file=sys.stderr)
            return 1

    if fields:
        print(as_tsv(body, fields))
    elif compact:
        print(json.dumps(body, separators=(",", ":"), ensure_ascii=False))
    else:
        print(json.dumps(body, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
