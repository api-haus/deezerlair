# PREFS — how you like your library

Copy this to `PREFS.md` and edit it. `PREFS.md` is gitignored, so it stays
yours and never collides with an upstream pull.

You do not have to edit it by hand. Tell the agent what you want — *"never add
a live version unless I say live"*, *"stop asking before you favourite
something"*, *"new playlists are private"* — and it will write the change here.

**On conflict, this file wins over `AGENTS.md`.** AGENTS.md describes how the
tools work and must not drift per-user; this file is taste.

## Which recording to pick

The studio original, by default. Not a live take, not a re-recording, not a
remaster when the original is available, not the compilation copy when the
album copy is there. A single edit only when the full version is missing.

Explicit lyrics are fine. Never substitute a clean edit for one.

This is a standing policy, not a per-title question: **do not ask me which
version I meant** when one of them is plainly the original. Ask only when the
choice is real — two different studio recordings, or a remix I might actually
have wanted.

> `dz_find.py` scores on name similarity and popularity. It does **not** know
> any of the above, and it strips words like "live" and "remaster" before it
> compares. So a live take can tie with the studio one. Whatever the script
> does not enforce, you enforce: read the titles in `--list` output and pick.

## Matching confidence

Below 0.6, show me the candidates instead of guessing. Above it, just act.

> The floor is `--min` on `dz_find.py`, `dz_playlist.py` and `dz_fav.py`,
> default 0.6. If you change the number here, pass `--min` or change the
> default in those scripts — that is a local edit to a tracked file, so keep
> it out of any PR you send upstream.

When a list I hand you has ISRCs in it, match on those and skip the scoring.

## Adding vs. asking

Add first, tell me after. Naming music is the request; I do not want to be
asked "shall I add this?" — that includes music the agent itself suggested a
moment earlier. Same for favouriting an artist I said I like.

Adding to a playlist does not mean favouriting the track as well. Keep those
two separate unless I say both.

## Removing

The other direction is not symmetrical. Take a snapshot, print the plan, and
wait for me. That covers deleting a playlist, dropping tracks, and merging
with `--drop-sources`.

Dead tracks — the ones this account can no longer play — are the exception in
reverse: **report them, do not remove them.** I want to see what fell out of
the catalogue before it goes, because sometimes a re-add finds it under a new
id.

## Playlists

New playlists are private until I say otherwise.

Titles: plain words, no emoji, no ALL CAPS, no "(2)" suffixes. If a transfer
left a name like "Liked from Spotify", rename it to what the list actually is.

Dedupe exact duplicates without asking once I have agreed to the cleanup.
Loose duplicates — the same song under two ids — need the plan shown first,
because picking which copy survives is a judgement call.

I would rather have fewer, larger, well-named playlists than many small ones.
When something is under about five tracks, it wants merging somewhere.

## Suggestions

Ground them in what is already in the library, and say which of my artists a
suggestion follows from. A handful at a time, not a wall.

Adventurous is fine — adjacent is better than obvious. Do not suggest
something already in a playlist or in the favourites; check first.

## Notes

Free-form. Anything that does not fit above goes here, in whatever shape suits
it.

**Only write here when I ask you to.** Do not keep a listening record, do not
infer what I like from the library, and do not add a line because you think
you noticed a pattern. Suggestions should come from what I tell you in the
conversation and from the library as it stands right now, not from a taste
profile you have been quietly building.
