#!/usr/bin/env python3
"""The authenticated transport: Deezer's own gw-light API, driven by an arl.

Deezer stopped handing out API applications, so the OAuth flow of the public
API cannot be completed by anybody who does not already have an application.
The site and the desktop player do not use that API — they use this one, and
they authenticate with a single cookie named `arl`.

That cookie is the whole session. Treat it as a password: it plays, it
downloads, and it edits the library. Never print it, never commit it.

    from dz_gw import Gw
    gw = Gw()
    gw.call("playlist.getSongs", PLAYLIST_ID=123, nb=100, start=0)

Read `dz.py` for the public half of the API — search, charts and catalogue
lookups need no session at all and return friendlier JSON.
"""
import http.cookiejar as cookiejar
import json
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSION_FILE = ROOT / "state" / "session.json"
GW = "https://www.deezer.com/ajax/gw-light.php"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")
WINDOW, BURST, RETRIES = 5.0, 40, 3
PAGE = 1000

# Deezer publishes no limit for the gateway and reports a breach in more than
# one shape, so anything that smells like throttling is treated as one: wait,
# then permanently slow this run down. A bulk job that takes a minute longer
# is better than one that stops half-finished.
THROTTLE_RETRIES = 8
THROTTLE_HINTS = ("quota", "rate limit", "ratelimit", "too many", "throttl",
                  "flood", "slow down", "temporarily", "try again",
                  "unavailable", "busy")
SPACING_FIRST = 0.25        # the delay imposed the first time we are told off
SPACING_MAX = 8.0
DECAY_AFTER = 40            # calls that must succeed before speeding up again


class Throttled(Exception):
    """Deezer asked us to slow down. Carries its own advice on how long."""

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


def looks_throttled(error):
    """True when a gateway error body is a rate limit wearing a costume."""
    text = json.dumps(error).lower() if not isinstance(error, str) else error.lower()
    return any(hint in text for hint in THROTTLE_HINTS)


def retry_after_seconds(headers):
    """Honour Retry-After when the server sends it, in either legal form."""
    raw = (headers or {}).get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        return max(0.0, parsedate_to_datetime(raw).timestamp() - time.time())
    except (TypeError, ValueError):
        return None

# Cookie stores that hold a live arl, best first. The Deezer desktop player
# does not encrypt its cookies, and neither does Firefox, so both can be read
# directly. Chromium-family browsers encrypt theirs — paste the arl by hand
# for those.
HOME = Path.home()
COOKIE_STORES = [
    ("Deezer desktop", HOME / ".config/Deezer/Cookies"),
    ("Deezer desktop (flatpak)",
     HOME / ".var/app/dev.aunetx.deezer/config/Deezer/Cookies"),
    ("Deezer desktop (snap)", HOME / "snap/deezer-desktop/current/.config/Deezer/Cookies"),
    ("Deezer desktop (macOS)", HOME / "Library/Application Support/Deezer/Cookies"),
    ("Deezer desktop (Windows)",
     Path(os.environ.get("APPDATA", "/nonexistent")) / "Deezer/Cookies"),
]


class GwError(RuntimeError):
    """An error the gateway reported inside the response body."""


def _firefox_profiles():
    for base in (HOME / ".mozilla/firefox",
                 HOME / "Library/Application Support/Firefox/Profiles",
                 Path(os.environ.get("APPDATA", "/nonexistent")) /
                 "Mozilla/Firefox/Profiles"):
        if base.is_dir():
            for profile in sorted(base.iterdir()):
                store = profile / "cookies.sqlite"
                if store.exists():
                    yield f"Firefox ({profile.name})", store


def read_arl(path):
    """Pull the arl out of one cookie store, or return None.

    The file is copied first: the browser or the player usually holds a lock
    on it, and a copy is also the only way to read it while it is running.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            copy = tmp.name
        shutil.copy(path, copy)
        db = sqlite3.connect(copy)
        for query in ("select value from cookies where name='arl'",
                      "select value from moz_cookies where name='arl'"):
            try:
                row = db.execute(query).fetchone()
            except sqlite3.Error:
                continue
            if row and row[0] and len(row[0]) > 100:
                return row[0]
        return None
    except (OSError, sqlite3.Error):
        return None
    finally:
        try:
            os.unlink(copy)
        except (OSError, UnboundLocalError, NameError):
            pass


def discover(quiet=True):
    """Every cookie store that currently holds an arl, best first."""
    found = []
    for label, path in list(COOKIE_STORES) + list(_firefox_profiles()):
        if Path(path).exists():
            arl = read_arl(path)
            if arl:
                found.append((label, str(path), arl))
            elif not quiet:
                print(f"  {label}: no arl in {path}", file=sys.stderr)
    return found


def load_session():
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text())
        except (ValueError, OSError):
            return {}
    return {}


def save_session(arl, user):
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps({
        "arl": arl,
        "stored": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "user_id": user.get("USER_ID"),
        "user_name": user.get("BLOG_NAME"),
        "loved_playlist_id": user.get("LOVEDTRACKS_ID"),
    }, indent=2) + "\n")
    SESSION_FILE.chmod(0o600)
    return SESSION_FILE


def resolve_arl():
    """Where the arl comes from, in order of preference."""
    if os.environ.get("DEEZER_ARL"):
        return os.environ["DEEZER_ARL"], "$DEEZER_ARL"
    stored = load_session().get("arl")
    if stored:
        return stored, str(SESSION_FILE)
    found = discover()
    if found:
        return found[0][2], found[0][0]
    return None, None


class Gw:
    """A paced gw-light session that repairs itself when the token expires."""

    def __init__(self, arl=None, verbose=False):
        self.verbose = verbose
        self.source = "given"
        if arl is None:
            arl, self.source = resolve_arl()
        if not arl:
            raise GwError(
                "no Deezer session — run the /deezer-login skill, or "
                "python3 scripts/dz_login.py")
        self.arl = arl
        self.token = "null"
        self._user = None
        self._calls = deque()
        self.spacing = 0.0          # extra delay between calls, grown on abuse
        self.throttles = 0          # how often Deezer told us off this run
        self._since_throttle = 0
        self._last_call = 0.0
        self._build_opener()

    # -- plumbing ---------------------------------------------------------

    def _build_opener(self):
        self.jar = cookiejar.CookieJar()
        self.jar.set_cookie(cookiejar.Cookie(
            0, "arl", self.arl, None, False, ".deezer.com", True, True,
            "/", False, True, None, False, None, None, {}))
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))

    def redact(self, text):
        return text.replace(self.arl, "<arl>") if self.arl else text

    def _pace(self):
        """Hold the burst window, plus whatever penalty this run has earned."""
        gap = time.monotonic() - self._last_call
        if self.spacing and gap < self.spacing:
            time.sleep(self.spacing - gap)
        now = time.monotonic()
        while self._calls and now - self._calls[0] > WINDOW:
            self._calls.popleft()
        if len(self._calls) >= BURST:
            time.sleep(WINDOW - (now - self._calls[0]) + 0.05)
            return self._pace()
        self._last_call = time.monotonic()
        self._calls.append(self._last_call)

    def _back_off(self, why, retry_after=None, attempt=1):
        """Wait out a throttle, and slow every later call down as well."""
        self.throttles += 1
        self._since_throttle = 0
        self.spacing = min(SPACING_MAX,
                           max(self.spacing * 2, SPACING_FIRST))
        wait = retry_after if retry_after is not None else min(
            60.0, 2 ** attempt + random.uniform(0, 1))
        print(f"deezer is throttling ({why}); waiting {wait:.1f}s, "
              f"pacing at {self.spacing:.2f}s between calls from here",
              file=sys.stderr)
        time.sleep(wait)

    def _went_well(self):
        """Earn the speed back slowly once Deezer stops complaining."""
        if not self.spacing:
            return
        self._since_throttle += 1
        if self._since_throttle >= DECAY_AFTER:
            self._since_throttle = 0
            self.spacing = 0.0 if self.spacing <= SPACING_FIRST else self.spacing / 2
            print(f"deezer settled down; pacing now {self.spacing:.2f}s",
                  file=sys.stderr)

    def _post(self, method, payload):
        url = GW + "?" + urllib.parse.urlencode(
            {"method": method, "input": "3", "api_version": "1.0",
             "api_token": self.token})
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(), method="POST",
            headers={"User-Agent": UA,
                     "Content-Type": "text/plain;charset=UTF-8",
                     "Accept": "*/*",
                     "Origin": "https://www.deezer.com",
                     "Referer": "https://www.deezer.com/"})
        self._pace()
        try:
            with self.opener.open(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                raise Throttled(f"HTTP {e.code}",
                                retry_after_seconds(e.headers)) from e
            raise

    def call(self, method, **payload):
        """Call one gateway method and return its `results`.

        Three things are handled here so no caller has to think about them: a
        stale CSRF token is refreshed and the call repeated, a throttle is
        waited out and the whole run slowed down, and a dropped connection is
        retried. Only a real refusal reaches the caller.
        """
        if self.token == "null" and method != "deezer.getUserData":
            self.user                       # opens the session, sets the token
        if self.verbose:
            print(f"gw {method} {json.dumps(payload)[:120]}", file=sys.stderr)
        network, throttled, last = 0, 0, None
        while True:
            try:
                body = self._post(method, payload)
            except Throttled as t:
                throttled += 1
                if throttled > THROTTLE_RETRIES:
                    raise GwError(f"{method}: still throttled after "
                                  f"{throttled} waits — try again later")
                self._back_off(f"{method}: {t}", t.retry_after, throttled)
                continue
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                network += 1
                last = str(e)
                if network > RETRIES:
                    raise GwError(f"{method}: gave up after {network} "
                                  f"tries: {last}")
                time.sleep(2 ** network + random.uniform(0, 0.5))
                continue

            error = body.get("error")
            if not error:
                self._went_well()
                return body.get("results")
            if isinstance(error, dict) and "VALID_TOKEN_REQUIRED" in error:
                self._user = None
                self.token = "null"
                self.user
                continue
            if looks_throttled(error):
                throttled += 1
                if throttled > THROTTLE_RETRIES:
                    raise GwError(f"{method}: still throttled after "
                                  f"{throttled} waits: {error}")
                self._back_off(f"{method}: {error}", None, throttled)
                continue
            raise GwError(f"{method}: {error}")

    # -- session ----------------------------------------------------------

    @property
    def user(self):
        """The logged-in user block, opening the session on first use."""
        if self._user is None:
            self.token = "null"
            results = self._post("deezer.getUserData", {}).get("results") or {}
            self.token = results.get("checkForm") or "null"
            self._user = results.get("USER") or {}
            if not self._user.get("USER_ID"):
                raise GwError(
                    f"the arl from {self.source} is not logged in — open the "
                    f"Deezer app, sign in, then run: "
                    f"python3 scripts/dz_login.py")
        return self._user

    @property
    def user_id(self):
        return self.user["USER_ID"]

    @property
    def name(self):
        return self.user.get("BLOG_NAME")

    @property
    def loved_playlist_id(self):
        """Deezer keeps the favourite tracks as an ordinary playlist."""
        return self.user.get("LOVEDTRACKS_ID")

    # -- paging -----------------------------------------------------------

    def paginate(self, method, nb=PAGE, cap=None, **payload):
        """Every row of a `{data, total}` method, walked with nb/start."""
        out, start = [], 0
        while True:
            results = self.call(method, nb=nb, start=start, **payload) or {}
            rows = results.get("data") or []
            out.extend(rows)
            total = results.get("total")
            if cap and len(out) >= cap:
                return out[:cap]
            if not rows or (total is not None and len(out) >= total):
                return out
            start += len(rows)

    def profile_tab(self, tab, nb=2000, user_id=None):
        """One tab of the profile page: playlists, albums, artists."""
        results = self.call("deezer.pageProfile", USER_ID=user_id or self.user_id,
                            tab=tab, nb=nb) or {}
        block = (results.get("TAB") or {}).get(tab) or {}
        return block.get("data") or []


# -- shapes ----------------------------------------------------------------
# The gateway speaks in SHOUTING_KEYS. Everything downstream speaks the slim
# vocabulary in CONTEXT.md, so translate once, here.

def as_track(row):
    """One gateway song row as the slim track the other scripts expect."""
    title = row.get("SNG_TITLE") or ""
    version = (row.get("VERSION") or "").strip()
    # VERSION carries "(Live)", "(Remastered)" and friends. Keep it: the
    # recording policy in PREFS.md cannot be applied without it.
    if version and version.lower() not in title.lower():
        title = f"{title} {version}".strip()
    size = str(row.get("FILESIZE") or "0")
    flac = str(row.get("FILESIZE_FLAC") or "0")
    return {"id": int(row["SNG_ID"]) if str(row.get("SNG_ID", "")).lstrip("-").isdigit()
            else row.get("SNG_ID"),
            "title": title,
            "artist": row.get("ART_NAME"),
            "artist_id": row.get("ART_ID"),
            "album": row.get("ALB_TITLE"),
            "album_id": row.get("ALB_ID"),
            "duration": int(row.get("DURATION") or 0),
            "isrc": row.get("ISRC") or None,
            "readable": size not in ("0", ""),
            "lossless": flac not in ("0", ""),
            "time_add": row.get("DATE_ADD")}


# Playlist STATUS, checked against what the public API will serve without a
# token: 0 is public, 1 is private. That is the opposite way round from what
# the name suggests, so do not "correct" it — a wrong guess here publishes
# every playlist the create command makes.
STATUS_PUBLIC, STATUS_PRIVATE = 0, 1


def as_playlist(row, me=None):
    """One gateway playlist row as the slim playlist shape."""
    parent = row.get("PARENT_USER_ID")
    status = int(row.get("STATUS") or 0)
    return {"id": int(row["PLAYLIST_ID"]) if str(row.get("PLAYLIST_ID", "")).isdigit()
            else row.get("PLAYLIST_ID"),
            "title": row.get("TITLE"),
            "nb_tracks": int(row.get("NB_SONG") or 0),
            "public": status == STATUS_PUBLIC,
            "collaborative": bool(row.get("IS_COLLABORATIVE")),
            "is_loved_track": bool(row.get("IS_LOVED_TRACK")),
            "creation_date": row.get("DATE_CREATE") or row.get("DATE_ADD"),
            "link": f"https://www.deezer.com/playlist/{row.get('PLAYLIST_ID')}",
            "creator_id": parent,
            "creator": row.get("PARENT_USERNAME"),
            "mine": str(parent) == str(me) if me is not None else None,
            "tracks": []}


def songs_payload(track_ids):
    """The gateway wants [[id, 0], ...] wherever it takes a list of songs."""
    return [[int(t), 0] for t in track_ids]


if __name__ == "__main__":
    # A quick look at the session, printing nothing secret.
    gw = Gw(verbose="-v" in sys.argv)
    print(f"user {gw.user_id} ({gw.name}), arl from {gw.source}")
    print(f"loved tracks playlist: {gw.loved_playlist_id}")
