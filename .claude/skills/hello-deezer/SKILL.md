---
name: hello-deezer
description: Brief a new user on their deezerlair preferences and write PREFS.md from their answers. Use on a fresh clone, whenever PREFS.md is missing, or when the user asks to set up, review or change their preferences.
---

# /hello-deezer — write PREFS.md with the user

The shipped defaults are one person's taste. Somebody else wants every remix
they can find, does not care about lossless, or would rather be asked before
anything touches their library. This is the conversation that finds that out
and writes it down.

Budget about a minute of the user's attention. A handful of questions with the
common answers offered, then a file. Not an interrogation, and not a form.

## 1. Read the shape from PREFS.example.md

`PREFS.example.md` is the source of truth for which preferences exist. **Read
it first, every time.** Each `##` section is one topic, and its prose states
the shipped default.

If the file disagrees with the table below, the file wins — it may have grown
a section since this skill was written. Ask about what is in the file, not
what is in here.

Skip the **Notes** section. It is free-form, it stays empty until the user
asks for something to go in it, and its whole point is that nobody fills it in
on their behalf.

## 2. Ask once, with concrete options

Four questions, in a single call so the user answers them together —
`AskUserQuestion` in Claude Code, a plain numbered list in any agent without
it. The sections you do not ask about keep the example's wording; say so at
the end rather than dragging the user through all of them.

How to write the options:

- The shipped default goes first, labelled `(Recommended)`.
- Describe outcomes the user recognises, not policy. *"The album version, not
  the live one"* beats *"prefer studio originals over live recordings"*.
- Three options is usually right. The user can always answer in their own
  words.
- **Never ask about taste** — not which artists they like, not what they
  listen to, not what to suggest. That is not what this file is for, and
  `PREFS.md` says so in its own closing section.

The mapping as `PREFS.example.md` stands today. Verify it against the file
before you use it:

| Section | Header | Question | Options |
|---|---|---|---|
| Which recording to pick | Recording | When several recordings of a song match, which should be added? | The studio original *(Recommended)* — never the live take or a remaster when the original exists · Whichever is most popular on Deezer · Ask each time there is a choice |
| Adding vs. asking | Autonomy | How much should it check with you before adding music? | Add first, tell you after *(Recommended)* · Confirm before every add · Confirm only for more than a handful at once |
| Audio quality | Lossless | What should happen when a track has no lossless version? | Add it anyway and mention it *(Recommended)* · Prefer a lossless copy elsewhere, and skip it if there is none · Do not mention it, lossless does not matter |
| Playlists | Playlists | How should new playlists be created, and how hard should duplicates be chased? | Private, and collapse only certain duplicates *(Recommended)* — same recording, matched by ISRC · Private, and also chase same-title duplicates · Public, and collapse only certain duplicates |

If the user has strong feelings about the confidence floor or about removal,
those are the **Matching confidence** and **Removing** sections — edit them
from what the user says rather than asking a fifth question up front.

## 3. Write PREFS.md

Copy `PREFS.example.md` and rewrite each section to match the answers. Keep
its structure, its headings and its voice — prose a person can read and edit,
not a config dump. A section the user took the default on keeps the example's
wording, minus the "Copy this to `PREFS.md`" opening, which becomes the
"Yours, and gitignored" line.

Two things carry over verbatim: the note that this file **overrides
`AGENTS.md`**, and the **Notes** section with its instruction never to keep a
listening record or infer taste. Those are not preferences.

## 4. Sync the code if a number moved

`PREFS.md` states policy in prose; a few scripts enforce it. A `PREFS.md` the
scripts disagree with is worse than no `PREFS.md` at all.

- **Matching confidence** is `FLOOR` at the top of `scripts/dz_find.py`. Every
  `--min` default in the repo reads from it, so that one line is the whole
  edit. Raise it for *"only add matches you are sure about"*, lower it for
  *"always add the best match"* — but never below about 0.3, where the search
  starts returning unrelated songs.
- **Playlist visibility** needs no edit: `dz_playlist.py create` is private
  unless `--public` is passed. If the user wants public by default, say that
  the flag is how to get it rather than inverting the default.
- **Lossless** needs no edit either: `better()` in `dz_playlist.py` already
  keeps the lossless copy of a duplicate.

Say which files you touched, if any.

## If PREFS.md already exists

Never clobber it. Read it, say in a sentence per section what it currently
sets, and ask which of them to revisit. Then edit those sections in place and
leave the rest alone.

A `PREFS.md` that is still a verbatim copy of `PREFS.example.md` counts as not
yet answered — say so, and offer the questions.

## Close

Confirm in a couple of lines what was written, and tell the user the file is
not something they have to maintain: saying *"stop adding live versions"* or
*"new playlists should be public"* in an ordinary session is enough, and the
agent will edit it for them.

Then get on with whatever they actually came for. If they opened the session
asking to clean up a playlist, clean up the playlist.
