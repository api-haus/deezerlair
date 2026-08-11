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
cp .env.example .env && chmod 600 .env
```

Register an application at <https://developers.deezer.com/myapps>:

- Application domain: `localhost`
- Redirect URL after authentication: `http://localhost:8080/deezerlair`

Put the Application ID and the Secret Key in `.env`, then log in:

```bash
python3 scripts/dz_login.py --serve      # opens a browser, catches the redirect
```

If you are working over SSH, or through an agent, use the two-step form
instead — `--url` prints the login link, and `--code` takes back the address
the browser landed on:

```bash
python3 scripts/dz_login.py --url
python3 scripts/dz_login.py --code 'http://localhost:8080/deezerlair?code=...'
```

The token is stored in `state/token.json`, mode 600, ignored by git. Deezer
issues it with `offline_access`, so it does not expire on a timer.

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
python3 scripts/dz_playlist.py create "Late Drive" --private
python3 scripts/dz_playlist.py add <id> --resolve tracklist.txt
python3 scripts/dz_playlist.py dedupe <id> --loose --apply
python3 scripts/dz_playlist.py merge <old> --into <new> --apply --drop-sources

# anything else the API can do
python3 scripts/dz.py artist/27/related --fields id,name
python3 scripts/dz.py -X POST playlist/<id>/tracks songs=3135556,916424
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

`AGENTS.md` is the operating guide — the safety rules, the common workflows,
and the API behaviour that is worth knowing before writing anything.
`CONTEXT.md` fixes the vocabulary. Both are written for
[Claude Code](https://claude.com/claude-code) but any agent that reads a
repository will get the same value from them.

`.claude/skills/deezer-login/` adds a `/deezer-login` command that walks a
user through the browser flow.

Then a session looks like: *"my library is a mess, what should I fix first"*,
or *"find me more like the Boards of Canada I already have and put it in a new
playlist"*.

## Safety

- A snapshot before any bulk write, in `snapshots/`, is the undo.
- Destructive commands are a dry run unless you pass `--apply`.
- Playlists the account follows but does not own are never written to.
- The token never leaves the machine and is redacted from verbose output.

## Notes on the API

Collected while building this, and expanded in `AGENTS.md`:

- A failed call returns HTTP 200 with an `error` object in the body.
- The quota is 50 calls per 5 seconds per application.
- Deleting a track from a playlist deletes every copy — the API addresses
  tracks by id, not by position.
- `readable: false` marks a track this account can never play.
- One redirect URL per application, and it cannot be changed after the fact.
- Write parameters go in the query string, including for POST and DELETE.

## Licence

MIT.
