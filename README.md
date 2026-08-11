# deezerlair

Manage a Deezer account from the terminal, or from an AI coding agent sitting
in this directory. Playlists, favourites, search, discovery, and the cleanup
that a library accumulated from other streaming services badly needs.

Plain Python 3, standard library only, no install step, official Deezer API.

It was built for the case where you moved to Deezer for the lossless audio and
the Linux desktop application, carried a decade of playlists in from Spotify,
Apple Music and YouTube Music, and ended up with forty lists called some
variation of "Liked Songs" — half of them the same tracks twice, and a good
number of tracks that will never play again.

## What it does not do

It does not download anything. It manages the library only: what is in it,
what it is called, and how it is arranged. Play and download in the Deezer
application.

## Setup

```bash
git clone https://github.com/api-haus/deezerlair && cd deezerlair
cp PREFS.example.md PREFS.md      # your taste; gitignored, edit freely
python3 scripts/dz_login.py
```

That is the whole setup, and usually there is nothing to paste.

**There is no API key, because you cannot get one.** Deezer has closed new
API application registration — <https://developers.deezer.com/myapps> answers
*"We're not accepting new application creation at this time"* — so the OAuth
flow in the official documentation cannot be started by anybody who does not
already own an application. Every write endpoint of the public API is behind
it, which makes that API read-only for new projects, permanently as far as
anyone outside Deezer can tell.

So this repo authenticates the way the Deezer website and desktop player do:
with a session cookie called `arl`. The desktop player stores its cookies
unencrypted, so **signing in to the player is the login** — `dz_login.py`
finds the cookie, checks it, and stores it in `state/session.json` (mode 600,
git-ignored). Firefox works the same way. For a Chromium-family browser, which
encrypts its cookie store, copy the value by hand:

```
deezer.com, signed in -> F12 -> Application -> Cookies -> arl -> copy
python3 scripts/dz_login.py --arl '<paste>'
```

**Treat the `arl` as your password.** It plays, downloads and edits the
library. Do not paste it into a chat, a commit or an issue. If it leaks, sign
out of Deezer everywhere to rotate it.

Reads of the catalogue — search, charts, an artist's related artists — go to
the public API and need no session at all.

## Use

```bash
# what is wrong with the library
python3 scripts/dz_pull.py --snapshot
python3 scripts/dz_audit.py

# find things
python3 scripts/dz_find.py "Boards of Canada - Roygbiv"
python3 scripts/dz_find.py USUG11600976            # an ISRC matches exactly
python3 scripts/dz_find.py --batch tracklist.txt   # a whole list at once

# favourites
python3 scripts/dz_fav.py add tracks --query "Air - La Femme d'Argent"
python3 scripts/dz_fav.py list artists

# playlists
python3 scripts/dz_playlist.py list
python3 scripts/dz_playlist.py create "Late Drive"          # private by default
python3 scripts/dz_playlist.py add <id> --resolve tracklist.txt
python3 scripts/dz_playlist.py dedupe <id> --apply           # same ISRC
python3 scripts/dz_playlist.py dedupe <id> --loose --apply   # same artist+title
python3 scripts/dz_playlist.py sort <id> --by artist --apply
python3 scripts/dz_playlist.py merge <old> --into <new> --apply --drop-sources

# anything else either API can do
python3 scripts/dz.py artist/27/related --fields id,name
python3 scripts/dz.py --gw playlist.getSongs PLAYLIST_ID=<id> nb=10 start=0
```

Everything that changes the account prints a plan and stops. Add `--apply`
(or `--yes` for a delete) to carry it out.

## Migrating a playlist from another service

Export it to a text file, one `Artist - Title` per line, or one ISRC per line.
Then:

```bash
python3 scripts/dz_find.py --batch exported.txt      # read what matched
python3 scripts/dz_playlist.py create "Imported"
python3 scripts/dz_playlist.py add <new-id> --resolve exported.txt
```

Matching is scored, and anything below 0.6 confidence is reported rather than
guessed at. ISRCs skip the guessing entirely, so use them when your export has
them.

## Use with an AI agent

A session looks like: *"my library is a mess, what should I fix first"*, or
*"find me more like the Boards of Canada I already have and put it in a new
playlist"*.

What makes that work is not the scripts — it is that the policy lives in
prose, in two files. `AGENTS.md` is the operating manual: the safety rules,
the common workflows, and the API behaviour worth knowing before writing
anything. It is the same for everyone. `PREFS.md` is yours — which recording
wins when several match, how much the agent should ask before acting, how you
want playlists named and suggestions pitched. It is gitignored, it overrides
`AGENTS.md` on any conflict, and it is the file the agent edits when you
change your mind:

- *"never add a live version unless I say live"*
- *"stop asking before you favourite something I just said I liked"*
- *"new playlists are private, and no emoji in the names"*

`CONTEXT.md` fixes the vocabulary, so "track", "song" and "loose duplicate"
mean one thing each. All of it is written for
[Claude Code](https://claude.com/claude-code), but any agent that reads a
repository gets the same value from it.

`.claude/skills/deezer-login/` adds a `/deezer-login` command that walks a
user through the browser flow.

## Safety

- A snapshot before any bulk write, in `snapshots/`, is the undo.
- Destructive commands are a dry run unless you pass `--apply`.
- Playlists the account follows but does not own are never written to.
- The token never leaves the machine and is redacted from verbose output.

## Notes on the API

Verified against a live account while building this, and expanded in
`AGENTS.md`. The gateway has no official documentation, so this is the part
worth keeping:

- New API application registration is closed, which makes the public API
  read-only for new projects. The gateway (`gw-light`) is the way in.
- A failed call still returns HTTP 200; the error is in the body.
- Playlist `STATUS` is **0 for public and 1 for private** — the opposite way
  round from what the name suggests. Getting this backwards publishes every
  playlist you create.
- Deezer refuses to hold the same track id twice in one playlist, so every
  duplicate is two different ids for one recording. Match them on ISRC, which
  gateway rows carry.
- `FILESIZE` of 0 means the track is unplayable for this account;
  `FILESIZE_FLAC` of 0 means there is no lossless version of it.
- `VERSION` holds "(Live)", "(Remastered)" and so on, separately from the
  title — so a title alone cannot tell you which recording you have.
- Gateway payloads are JSON in the POST body, so nothing is capped by URL
  length: a playlist of any size reorders in a single call.

## Licence

MIT — see [LICENSE.md](LICENSE.md).
