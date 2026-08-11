# deezerlair — agent operating guide

Tools to manage one Deezer account from a terminal: playlists, favourites,
search and discovery. Everything is plain Python 3 with no dependencies, and
every script calls the official Deezer API through `scripts/dz.py`.

The owner listens and downloads in the Deezer desktop application. This repo
never touches audio. It manages the *library* — what is in it, how it is
named, and how it is organised.

@PREFS.md

The user's standing preferences live in `PREFS.md` — which recording to pick,
how much to ask before acting, playlist naming and hygiene, how suggestions
should behave. **It is gitignored and it overrides this file on any
conflict.** When the user tells you to change a preference, edit `PREFS.md`,
not this file — this file is shared doctrine and must not pick up one person's
settings. If `PREFS.md` is missing, copy `PREFS.example.md` to it first.

Write to `PREFS.md` only on an explicit instruction. It is not a place to
record what the user listens to or to log inferences about their taste.

## Start of a session

Check that the token is alive before anything else:

```bash
python3 scripts/dz_login.py --check
```

If it reports no token or a dead token, run the `/deezer-login` skill. Do not
try to log in by hand — the flow needs the human to open a browser.

Then, for any question about the shape of the library, refresh the cache once
and read that instead of the API:

```bash
python3 scripts/dz_pull.py --snapshot     # cache + a restore point
python3 scripts/dz_audit.py               # what is wrong, and the fix
```

## Default to acting

When the user names music they want — a track, an album, an artist, a mood
they ask you to fill — find it and add it. That is the default action, not a
question. Adding is cheap and one command removes it again.

```bash
python3 scripts/dz_fav.py add tracks --query "Air - La Femme d'Argent"
python3 scripts/dz_playlist.py add 12345 --query "Aphex Twin - Xtal"
```

Only stop and ask when the request is ambiguous about *which* recording, and
the candidates differ in a way the user would care about — a live version
against the studio one, an edit against the full length. A confidence below
the floor in `PREFS.md` is the signal: show the candidates, let the user pick.

Which recording wins when several match, and how far "act, don't ask" goes,
are both set in `PREFS.md`; if it asks for more confirmation than the above,
follow it.

Removing is the opposite. Take a snapshot first, print the plan, and let the
plan run only after the user agrees. Every destructive command already
defaults to a dry run for this reason.

## The scripts

| Script | What it does |
| --- | --- |
| `dz.py` | Any API call at all. Everything else imports it. |
| `dz_login.py` | The OAuth flow, and `--check` to test the token. |
| `dz_find.py` | Free text or an ISRC to an id, with a confidence. |
| `dz_pull.py` | The whole library into `cache/library.json` and snapshots. |
| `dz_audit.py` | Finds duplicates, overlaps, dead tracks and twin playlists. |
| `dz_playlist.py` | Create, fill, rename, dedupe, merge, sort, delete. |
| `dz_fav.py` | Favourite tracks, albums and artists. |

`dz.py` reaches anything the other scripts do not cover:

```bash
python3 scripts/dz.py user/me/history --fields title,artist.name --max 50
python3 scripts/dz.py artist/27/related --fields id,name
python3 scripts/dz.py -X POST playlist/12345/tracks songs=3135556,916424
```

## Keep the output small

A playlist of 900 tracks as raw JSON is worthless in a context window. Always
project the fields you need:

```bash
python3 scripts/dz.py --all user/me/playlists --fields id,title,nb_tracks
```

For anything that spans the whole library — counting, grouping, comparing
playlists — read `cache/library.json` with a short Python snippet. It holds
every playlist and every track, it costs no quota, and it is much faster than
walking the API again.

## Common work

**Clean one playlist**

```bash
python3 scripts/dz_playlist.py dedupe 12345 --loose      # plan
python3 scripts/dz_playlist.py dedupe 12345 --loose --apply
```

**Fold a transferred playlist into the one that replaced it**

```bash
python3 scripts/dz_playlist.py merge 111 --into 222       # plan
python3 scripts/dz_playlist.py merge 111 --into 222 --apply --drop-sources
```

**Build a playlist from a list of songs in a file**

```bash
python3 scripts/dz_find.py --batch wanted.txt             # check the matches
python3 scripts/dz_playlist.py create "Late Drive" --private
python3 scripts/dz_playlist.py add <new-id> --resolve wanted.txt
```

Read the `--batch` output before you write anything. Lines with an empty id
did not resolve, and lines with a low confidence resolved to the wrong song
often enough to be worth a look. `PREFS.md` sets where that floor sits and
what to do with the lines that fall under it.

**Discovery and suggestions**

```bash
python3 scripts/dz.py artist/27/related --fields id,name
python3 scripts/dz.py artist/27/radio --fields id,title,artist.name
python3 scripts/dz.py --all user/me/recommendations/tracks --fields id,title,artist.name
python3 scripts/dz.py chart/0/tracks limit=20 --fields id,title,artist.name
python3 scripts/dz.py editorial/0/releases limit=20 --fields id,title,artist.name
```

Ground a suggestion in what the account already holds. The `artists` section
of `dz_audit.py` names who dominates the library; `artist/<id>/related` and
`artist/<id>/radio` expand outwards from there. Say why each suggestion
follows from something the user already keeps.

How many suggestions at a time, how far from the familiar to reach, and what
to leave alone are in `PREFS.md`. Read the library live for this — never build
a stored profile of the user's taste.

## Hard rules

- **Take a snapshot before any bulk write.** `python3 scripts/dz_pull.py
  --snapshot` writes `snapshots/<timestamp>.json`. To undo, read the track ids
  back out with `dz_pull.py --ids <playlist> --from snapshots/<file>.json` and
  feed them to `dz_playlist.py add`. Without a snapshot a wrong merge is not
  recoverable.
- **`dz_find.py` enforces only part of `PREFS.md`.** It scores name similarity
  and popularity, and it deliberately strips words like "live", "remaster" and
  "radio edit" before it compares — so a live take or a remaster can tie with
  the studio original and win on popularity alone. Whatever the script does
  not enforce, you enforce: read the titles in `--list` output and pick the
  one the preferences ask for, rather than handing the user a choice they have
  already made in `PREFS.md`.
- **Never edit a playlist the account does not own.** `dz_playlist.py list`
  marks them in the `mine` column, and `dz_audit.py` ignores them. A followed
  playlist belongs to somebody else, and the API will refuse the write anyway.
- **The favourite tracks and the "Loved Tracks" playlist are one list.** Use
  `dz_fav.py` for it. Adding tracks to it through `dz_playlist.py` treats it
  as an ordinary playlist and confuses the two views of the same data.
- **Deleting a track from a playlist deletes every copy of it.** The API takes
  track ids, not positions, so one copy of a duplicate cannot be singled out.
  `dz_playlist.py dedupe` handles this by deleting the id and adding it back
  once; the surviving copy lands at the end of the playlist. Accept that, or
  do not dedupe that playlist.
- **`playlist delete` is final.** Deezer keeps no trash. It needs `--yes`, and
  it needs a snapshot taken first.
- **Never print or commit the access token.** It lives in `state/token.json`
  (mode 600) and `.env`, both ignored by git. `dz.py` redacts it from verbose
  output; keep it that way.
- **Respect the quota.** Deezer allows 50 calls per 5 seconds per
  application. `dz.py` paces itself and retries, so use it rather than raw
  `curl`. A loop of one call per track is fine; a loop that bypasses `dz.py`
  is not.
- **Do not add downloading to this repo.** The desktop application does that,
  and keeping this project to the documented API is what keeps it publishable.

## API notes worth knowing

- A failed call still returns HTTP 200 with an `error` object in the body.
  Never judge success by the status code. `dz.py` raises on it for you.
- `readable: false` means the account cannot play that track — usually a
  licensing gap, and very common in a playlist transferred from another
  service. Treat those tracks as dead weight; `dz_audit.py` lists them.
- List endpoints page with `index` and `limit` and carry a `next` link.
  `dz.py --all` follows it. Never assume the first page is everything.
- Write parameters go in the query string, not in a body — including for
  `POST` and `DELETE`. `songs=` takes a comma-separated list, and the scripts
  send it in batches of 50 so the URL stays inside the server's limit.
- Reordering sends the whole track list in one `order=` parameter, so it only
  works for a playlist of a few hundred tracks. `dz_playlist.py sort` refuses
  above 400 and says so.
- Search accepts fielded queries: `q=artist:"boards of canada" track:"roygbiv"`,
  plus `dur_min`, `dur_max`, `bpm_min`, `bpm_max` and `label`. Add
  `order=RANKING` or a `*_ASC` / `*_DESC` variant to sort the results.
- An ISRC identifies a recording exactly across services:
  `dz.py track/isrc:USUG11600976`. When a user brings a list exported from
  another platform with ISRCs in it, match on those and skip the guessing.
- `user/me/permissions` reports what the token may do. If a write fails with
  an OAuth error, check there before debugging anything else.

## Layout

- `scripts/` — everything above, stdlib only, no install step
- `PREFS.md` — the user's taste, gitignored, wins over this file
- `PREFS.example.md` — the tracked template it is copied from
- `.claude/skills/deezer-login/` — the browser login flow
- `.env` — application id and secret (mode 600, ignored by git)
- `state/token.json` — the access token (mode 600, ignored by git)
- `cache/library.json` — the last pull, safe to delete and rebuild
- `snapshots/` — restore points, the undo for everything destructive
