---
name: deezer-login
description: Connect this repo to a Deezer account, or repair a broken connection. Use when a script reports no session, when `dz_login.py --check` fails, when writes stop working, or when the user asks to log in, re-authorise or switch account.
---

# /deezer-login — connect the account

There is no OAuth here, and do not try to build one. Deezer has closed new API
application registration, so the documented flow cannot be started by anyone
who does not already own an application. The website and the desktop player
authenticate with a single cookie called `arl`, and so does this repo.

Usually there is nothing to paste. The Deezer desktop player stores its
cookies unencrypted, so **signing in to the player is the login**, and the
scripts read the cookie out of it. Firefox works the same way.

## Step 1 — see what is there

```bash
python3 scripts/dz_login.py --check
```

- It names an account and an audio quality — the connection works. Say so and
  stop, unless the user wants a different account.
- It says there is no session, or the session is dead — go to step 2.

## Step 2 — connect

```bash
python3 scripts/dz_login.py
```

This searches every cookie store it knows, verifies the first live `arl` it
finds, and stores it. If it succeeds, confirm the account name back to the
user and go to step 4.

If it finds nothing, run `python3 scripts/dz_login.py --where` to show which
stores were searched, then pick the case that applies:

- **The player is installed but not signed in.** Ask the user to open the
  Deezer desktop player and sign in, then run step 2 again.
- **The player is not installed, but the user has Firefox.** Ask them to sign
  in to deezer.com in Firefox, then run step 2 again.
- **The user only has Chrome, Brave, Edge or another Chromium browser.** Those
  encrypt their cookie store, so the cookie has to come across by hand — go to
  step 3.

## Step 3 — paste the cookie by hand

Ask the user to do this on deezer.com while signed in, in their own words:

> Press F12, open **Application** (Chrome) or **Storage** (Firefox), expand
> **Cookies**, choose `https://www.deezer.com`, find the row named **arl**,
> and copy its value. It is a long line of about 192 hexadecimal characters.

Then:

```bash
python3 scripts/dz_login.py --arl '<the value they pasted>'
```

**The `arl` is the entire account.** It plays, it downloads, and it edits the
library. Never echo it back into the conversation, never write it into a file
other than `state/session.json`, and never put it in a commit. If the user
pastes it in chat, tell them plainly that they should rotate it later by
signing out of Deezer everywhere, and carry on.

## Step 4 — leave the account ready

```bash
python3 scripts/dz_login.py --check
python3 scripts/dz_pull.py --snapshot
```

The pull fills `cache/library.json` and writes the first restore point, which
every destructive command later depends on.

## When it breaks later

An `arl` rotates when the user signs out everywhere or changes their password.
The symptom is a script saying the session is not logged in.

The repair is always the same: have the user sign in to the Deezer player
again, then run `python3 scripts/dz_login.py` to pick up the fresh cookie.
`--forget` drops the stored one first if you want a clean start.
