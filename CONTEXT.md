# Ubiquitous language

The words below mean one thing in this repo. Use them, in code and in
conversation, and do not introduce synonyms for them.

**track** — one recording, identified by a Deezer track id. The same song
released on a single, on an album and on a remaster is three tracks with three
ids. Ids are the only reliable handle; titles are not.

**song** — what a listener means by "the same song": the artist name and the
title, folded to lowercase with the punctuation and the decoration removed
(`norm()` in `dz_find.py`). Two tracks can be one song.

**readable** — the account can play this track. `readable: false` means a
licensing gap in this country. Those tracks stay in a playlist forever and
never play, and a transfer from another service brings many of them.

**duplicate** — two different track ids in one playlist for what a listener
hears as one song. Deezer refuses to hold one id twice, so there is no other
kind. A **same-recording duplicate** shares an ISRC and is safe to collapse; a
**same-song duplicate** matches only on artist and title, and may turn out to
be a cover or a re-recording. This is what a playlist transfer produces.

**lossless** — a FLAC exists for this track. The gateway reports it as a
non-zero `FILESIZE_FLAC`. A track can be perfectly playable and still have no
lossless version.

**own playlist** — created by this account, and writable. **followed
playlist** — created by somebody else and saved to this account. Both appear
in `user/me/playlists`; only the first can be changed.

**favourites** — the account's loved tracks, albums and artists. The
favourite tracks and the playlist named "Loved Tracks" are two views of one
list, not two lists.

**cache** — `cache/library.json`, the last full copy of the library. It is
disposable and rebuilt by `dz_pull.py`.

**snapshot** / **restore point** — a timestamped copy of the same structure in
`snapshots/`. It is the undo for anything destructive, and the reason bulk
writes are safe to attempt.

**confidence** — how well a search result answers a text query, from 0 to 1,
from `dz_find.py`. 1.0 is an exact match on artist and title, or an ISRC hit.
Below 0.6 the match is a guess and needs a human eye.

**plan** — what a destructive command prints when it runs without `--apply`:
the exact changes it would make. Every such command defaults to this.

**preference** — a standing decision of the account owner, kept in `PREFS.md`.
It is taste, it is personal to one user, and it overrides `AGENTS.md`, which
is shared doctrine. A preference is written down only when the owner asks for
it, never inferred.

**arl** — the cookie that is the whole Deezer session. It plays, downloads and
edits the library, so it is a password, not a token. It comes from the desktop
player's cookie store, and lives in `state/session.json`.

**gateway** — `gw-light`, the private API the Deezer website talks to. It
answers in SHOUTING_KEYS and is reached through `dz_gw.py`. The **public API**
is `api.deezer.com`: no session, clean JSON, catalogue only.
