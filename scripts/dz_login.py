#!/usr/bin/env python3
"""Connect this repo to a Deezer account by finding its session cookie.

    python3 scripts/dz_login.py            find the arl, verify it, store it
    python3 scripts/dz_login.py --check    who is connected, and what they get
    python3 scripts/dz_login.py --where    which cookie stores were found
    python3 scripts/dz_login.py --arl ...  store one pasted by hand
    python3 scripts/dz_login.py --forget   drop the stored session

There is no OAuth here. Deezer closed new API application registration, so the
documented flow cannot be started by anyone who has no application already.
The site and the desktop player authenticate with one cookie called `arl`, and
so does this repo.

Normally nothing needs to be pasted: the Deezer desktop player keeps its
cookies unencrypted, so signing in there is the login. Firefox works too.
Chromium-family browsers encrypt their cookie store, so for those, copy the
arl by hand:

    deezer.com, signed in -> F12 -> Application -> Cookies -> arl -> copy

The arl is the entire account. It plays, it downloads, and it edits the
library. This script never prints it, and `state/session.json` is mode 600 and
ignored by git. Keep it that way.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dz_gw import (SESSION_FILE, Gw, GwError, discover, load_session,
                   save_session)


def report(gw):
    """Say who is connected and what the account can do."""
    user = gw.user
    options = user.get("OPTIONS") or {}
    quality = ("lossless" if options.get("web_lossless") else
               "high" if options.get("web_hq") else "standard")
    print(f"connected as {gw.name} (id {gw.user_id}, "
          f"{user.get('RECOMMENDATION_COUNTRY', '?')}), audio: {quality}")
    print(f"favourite tracks live in playlist {gw.loved_playlist_id}")
    return 0


def connect(arl=None):
    """Verify an arl and store it."""
    try:
        gw = Gw(arl=arl)
        gw.user
    except GwError as e:
        print(f"login failed: {e}", file=sys.stderr)
        return 1
    path = save_session(gw.arl, gw.user)
    print(f"arl taken from {gw.source}")
    report(gw)
    print(f"session stored in {path} (mode 600, git-ignored)")
    return 0


def where():
    """List cookie stores holding an arl. Prints no secrets."""
    found = discover(quiet=False)
    if not found:
        print("no arl found in any known cookie store.\n"
              "Sign in to the Deezer desktop player or to deezer.com in "
              "Firefox, then run this again. For a Chromium-family browser, "
              "copy the cookie by hand and use --arl.")
        return 1
    for label, path, arl in found:
        print(f"  {label:30} {path}  (arl {len(arl)} chars)")
    stored = load_session()
    if stored.get("arl"):
        print(f"\nstored session: {stored.get('user_name')} "
              f"(id {stored.get('user_id')}), written {stored.get('stored')}")
    return 0


def check():
    try:
        gw = Gw()
    except GwError as e:
        print(e, file=sys.stderr)
        return 1
    try:
        return report(gw)
    except GwError as e:
        print(f"the stored session is dead: {e}\n"
              f"Sign in to the Deezer player again, then run: "
              f"python3 scripts/dz_login.py", file=sys.stderr)
        return 1


def forget():
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
        print(f"removed {SESSION_FILE}")
    else:
        print("nothing stored")
    return 0


def main(argv):
    if not argv:
        return connect()
    mode = argv[0]
    if mode in ("-h", "--help"):
        print(__doc__)
        return 0
    if mode == "--check":
        return check()
    if mode == "--where":
        return where()
    if mode == "--forget":
        return forget()
    if mode == "--arl":
        if len(argv) < 2 or len(argv[1]) < 100:
            sys.exit("--arl needs the cookie value, which is a long "
                     "hexadecimal string (about 192 characters)")
        return connect(argv[1].strip())
    sys.exit(f"unknown option {mode!r}\n\n{__doc__}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
