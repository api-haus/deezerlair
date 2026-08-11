# deezerlair — agent operating guide

This is the tool-neutral source of truth for AI agents in this repo. Every
agent reads it, either directly or through a one-line adapter file:
`CLAUDE.md` imports it and adds nothing but Claude-specific notes.

Tools to manage one Deezer account from a terminal: playlists, favourites,
search and discovery. Everything is plain Python 3 with no dependencies.

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

If there is no `PREFS.md` — or it is still a verbatim copy of
`PREFS.example.md`, which means nobody has answered anything — mention
`/hello-deezer` once, lightly, at a natural pause, and never as a gate on the
thing they asked for. *"You have no PREFS.md yet; `/hello-deezer` sets how
much to ask before adding, and which recording wins, in about a minute."* If
they opened the session asking to fix a playlist, fix the playlist first and
mention it after. Do not ask the preference questions inline instead: that is
what the skill is for, and asked ad hoc they end up answered but unrecorded.

## Provider-neutral by default

- Durable guidance goes in this file, not in a provider's own.
- Skills live in `.agents/skills/` and `.claude/skills/` as byte-identical
  copies — Claude Code loads only the second, other agents have no reason to
  look there. Edit either, then sync and check:
  `rsync -a --delete .claude/skills/ .agents/skills/` followed by
  `python3 scripts/selftest.py`, which fails when the two drift apart.
- Keep provider-specific notes to the adapter file (`CLAUDE.md`) and personal
  settings out of git entirely.

## Two APIs, and which one to use

Deezer has a public API and a private one, and this repo uses both.

- **`api.deezer.com`** — public, no session, clean JSON. Search, catalogue
  lookups, charts, editorial, related artists. `dz.py` and `dz_find.py` speak
  it. Its *write* endpoints need an OAuth token, and **Deezer has closed new
  API application registration**, so that half is unreachable. Do not try to
  build the OAuth flow; it cannot be completed.
- **gw-light** — the gateway the Deezer website itself uses, authenticated by
  the `arl` cookie. Everything about the account, and every write, happens
  here. `dz_gw.py` speaks it, and `dz.py --gw <method>` reaches it directly.

Ids are the same in both, so a track found through search can be written
through the gateway without translation.

## First run — setting this up

Someone opening a session here with nothing configured is a normal request,
not a special occasion. Work through this and ask only for what you cannot
know:

1. `python3 scripts/dz_login.py --check` — if it names an account, skip to 3.
2. Run `/deezer-login`. It usually needs nothing but the user being signed in
   to the Deezer desktop player.
3. `cp PREFS.example.md PREFS.md` then run `/hello-deezer`, which turns four
   questions into that file.
4. `python3 scripts/dz_pull.py --snapshot` — fills the cache and writes the
   first restore point.
5. `python3 scripts/dz_audit.py` — tells them what is wrong with the library.

Then ask what they want to do with it.

## Start of a session

Check that the session is alive before anything else:

```bash
python3 scripts/dz_login.py --check
```

If it reports no session or a dead one, run the `/deezer-login` skill. The
usual repair is for the user to sign in to the Deezer desktop player again —
the scripts read the cookie straight out of it.

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
| `dz.py` | The public API, plus `--gw` for any gateway method. |
| `dz_gw.py` | The authenticated transport. Everything writing imports it. |
| `dz_login.py` | Finds the `arl`, verifies it, stores it. `--check` tests it. |
| `dz_find.py` | Free text or an ISRC to an id, with a confidence. |
| `dz_pull.py` | The whole library into `cache/library.json` and snapshots. |
| `dz_audit.py` | Duplicates, overlaps, dead and lossy tracks, twin playlists. |
| `dz_playlist.py` | Create, fill, rename, dedupe, merge, sort, delete. |
| `dz_fav.py` | Favourite tracks, albums and artists. |
| `selftest.py` | Offline checks of the pure logic. Run it after editing them. |

`dz.py` reaches anything the other scripts do not cover, on either API:

```bash
python3 scripts/dz.py artist/27/related --fields id,name
python3 scripts/dz.py chart/0/tracks limit=20 --fields title,artist.name
python3 scripts/dz.py --gw deezer.pageProfile USER_ID=<id> tab=albums nb=5
python3 scripts/dz.py --gw playlist.getSongs PLAYLIST_ID=<id> nb=10 start=0
```

Gateway methods worth knowing, all verified against a live account:
`deezer.getUserData`, `deezer.pageProfile` (tabs `playlists`, `albums`,
`artists`), `deezer.pagePlaylist`, `playlist.getSongs`, `playlist.create`,
`playlist.addSongs`, `playlist.deleteSongs`, `playlist.update`,
`playlist.updateOrder`, `playlist.delete`, `favorite_song.add` / `.remove`,
`album.addFavorite` / `.deleteFavorite`, `artist.addFavorite` /
`.deleteFavorite`, `playlist.addFavorite` / `.deleteFavorite`.

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

**Change visibility in bulk**

```bash
python3 scripts/dz_playlist.py privacy private --all          # plan
python3 scripts/dz_playlist.py privacy private --all --apply
python3 scripts/dz_playlist.py privacy public 12345 --apply   # named ones
```

It reads the current state each run and touches only what is still wrong, so
an interrupted run is resumed by running it again. It rewrites the whole
playlist header, and reads each header first for exactly that reason — see the
hard rule below.

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
- **The favourite tracks and the "Loved Tracks" playlist are one list.** Its
  id is on the session (`gw.loved_playlist_id`). Use `dz_fav.py` for it.
- **A duplicate is never the same id twice.** Deezer refuses to hold one track
  id twice in a playlist, so duplicates are always two different ids for one
  recording. Matching ISRCs prove it is the same recording and are safe to
  collapse; matching artist and title (`--loose`) also catch re-recordings and
  covers, so show that plan before applying it.
- **`playlist delete` is final.** Deezer keeps no trash. It needs `--yes`, and
  it needs a snapshot taken first.
- **Never print or commit the `arl`.** It is the whole account — it plays,
  downloads and edits. It lives in `state/session.json` (mode 600, ignored by
  git) or is read live from the desktop player. `dz_gw.py` redacts it; keep it
  that way, and never paste it into a chat, a commit or a log.
- **`playlist.update` replaces the whole header.** Any field you leave out is
  wiped — omitting `description` empties it, and omitting `title` is rejected
  outright. Never call it directly: `dz_playlist.update()` reads the current
  header and sends back what is not changing. This is proven behaviour, not a
  precaution.
- **Pace the writes, and let the throttle handle itself.** `dz_gw.py` stays
  under 40 calls per 5 seconds, and when Deezer pushes back — an HTTP 429 or
  503, or a body that mentions a quota — it waits (honouring `Retry-After`),
  doubles the delay between every later call, and carries on, earning the
  speed back after 40 clean calls. So a long bulk job is safe to start and
  will simply take longer under pressure. Never bypass it with raw `curl`, and
  never wrap a script in a retry loop of your own: that fights the pacer
  instead of helping it. `Gw.throttles` counts how often it happened.
- **Do not add downloading to this repo.** The desktop application does that,
  and keeping this project to the documented API is what keeps it publishable.

## API notes worth knowing

All of the below was checked against a live account, not taken from a
document. The gateway has no official documentation, so when something here
disagrees with what you observe, believe what you observe and fix this file.

- **A failed call still returns HTTP 200.** The public API puts an `error`
  object in the body; the gateway puts one in `error`, and an empty list there
  means success. Never judge either by the status code.
- **Playlist `STATUS` is 0 for public and 1 for private** — the opposite way
  round from what the name suggests. It is verified by asking the public API
  for the playlist without a token: it serves a public one and refuses a
  private one. Do not "correct" this constant.
- **The gateway pages with `nb` and `start`**, and returns `{data, total}`.
  `Gw.paginate` walks it. The public API pages with `index` and `limit` and a
  `next` link, which `dz.py --all` follows. Never assume one page is all.
- **Gateway payloads are JSON in the POST body**, so there is no URL length
  limit: `playlist.updateOrder` reorders a playlist of any size in one call,
  and `songs` takes `[[track_id, 0], ...]` however long.
- **A CSRF token expires before the session does.** `Gw.call` refreshes it and
  repeats the call when the gateway answers `VALID_TOKEN_REQUIRED`.
- **`FILESIZE` of 0 means the account cannot play that track** — the gateway
  has no `readable` field. `FILESIZE_FLAC` of 0 means there is no lossless
  version. `dz_gw.as_track` turns those into `readable` and `lossless`.
- **Gateway track rows carry the ISRC**, which identifies a recording exactly
  across services. It is the best duplicate signal there is, and the right way
  to match a list exported from another platform. The public API exposes it as
  `dz.py track/isrc:USUG11600976`.
- **`VERSION` holds "(Live)", "(Remastered)" and friends**, separate from
  `SNG_TITLE`. `as_track` appends it, because the recording policy in
  `PREFS.md` cannot be applied to a title that has been stripped of it.
- Search accepts fielded queries: `q=artist:"boards of canada" track:"roygbiv"`,
  plus `dur_min`, `dur_max`, `bpm_min`, `bpm_max` and `label`. Add
  `order=RANKING` or a `*_ASC` / `*_DESC` variant to sort the results.
- Adding a track that is already in a playlist is a silent no-op, so `add` is
  safe to repeat.

## Layout

- `scripts/` — everything above, stdlib only, no install step
- `PREFS.md` — the user's taste, gitignored, wins over this file
- `PREFS.example.md` — the tracked template it is copied from
- `CLAUDE.md` — the Claude adapter; imports this file, adds nothing else
- `.agents/skills/`, `.claude/skills/` — `deezer-login` and `hello-deezer`,
  kept identical in both
- `state/session.json` — the `arl` (mode 600, ignored by git)
- `cache/library.json` — the last pull, safe to delete and rebuild
- `snapshots/` — restore points, the undo for everything destructive
