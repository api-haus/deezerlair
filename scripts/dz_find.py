#!/usr/bin/env python3
"""Turn free text into Deezer ids — the bridge between a request and an id.

Usage:
    dz_find.py "Boards of Canada - Roygbiv"       best match, as TSV
    dz_find.py --list "roygbiv"                   top candidates, ranked
    dz_find.py --id-only "Aphex Twin - Xtal"      just the id, for scripts
    dz_find.py --kind album "Daft Punk Discovery"
    dz_find.py --batch tracklist.txt              one query per line
    dz_find.py --batch -                          read the lines from stdin
    dz_find.py USUG11600976                       an ISRC resolves exactly

Query text is split on " - ", " – " or " by " into artist and title, and sent
as a fielded search. The fallback is a plain search over the whole string.

Every candidate gets a confidence between 0 and 1. Below the floor (FLOOR
below, 0.6 as shipped) the match is a guess: show it to the user instead of
writing it into a playlist. Tracks this account cannot play are dropped
unless you pass --any.
"""
import argparse
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dz import Deezer, DeezerError, cell

# How sure a match must be before a script will write it into the library.
# This is a preference, not a constant of nature: `PREFS.md` states it in
# prose and this is what enforces it, so the two move together. Every --min
# default in this repo reads from here.
FLOOR = 0.6

SPLIT = re.compile(r"\s+[-–—]\s+|\s+by\s+", re.I)
ISRC = re.compile(r"^[A-Za-z]{2}[A-Za-z0-9]{3}\d{7}$")
# Decoration that survives a playlist transfer and ruins a literal match.
NOISE = re.compile(
    r"\((feat|ft|with|remaster|remastered|deluxe|live|bonus|mono|stereo)[^)]*\)"
    r"|\[(feat|ft|with|remaster|remastered|deluxe|live|bonus)[^\]]*\]"
    r"|\s-\s(19|20)\d{2}\s+(digital\s+)?remaster(ed)?.*$"
    r"|\s-\s(remaster(ed)?|single version|album version|radio edit).*$",
    re.I)

KINDS = ("track", "album", "artist", "playlist", "podcast", "radio", "user")
FIELDS = {
    "track": ["id", "title", "artist.name", "album.title", "duration",
              "readable"],
    "album": ["id", "title", "artist.name", "nb_tracks", "release_date"],
    "artist": ["id", "name", "nb_album", "nb_fan"],
    "playlist": ["id", "title", "user.name", "nb_tracks"],
    "podcast": ["id", "title", "description"],
    "radio": ["id", "title"],
    "user": ["id", "name"],
}


def norm(text):
    """Fold a title down to what two spellings of it have in common."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = NOISE.sub("", text.lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def ratio(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # A title contained whole in the other side is a near miss, not a mismatch.
    contained = 0.9 if (a in b or b in a) else 0.0
    return max(contained, SequenceMatcher(None, a, b).ratio())


def split_query(text):
    """Return (artist, title). Either half may be empty."""
    parts = SPLIT.split(text.strip(), maxsplit=1)
    if len(parts) == 2 and all(p.strip() for p in parts):
        return parts[0].strip(), parts[1].strip()
    return "", text.strip()


def confidence(row, artist, title, kind):
    """How well one candidate answers the query, from 0 to 1."""
    if kind == "artist":
        return ratio(row.get("name"), title or artist)
    got_title = ratio(row.get("title"), title)
    if not artist:
        return got_title
    got_artist = ratio((row.get("artist") or {}).get("name"), artist)
    return 0.6 * got_title + 0.4 * got_artist


def search(client, text, kind="track", limit=25, allow_unplayable=False):
    """Return candidates for one query, best first, each with a confidence."""
    artist, title = split_query(text)
    tries = []
    if kind == "track" and artist:
        tries.append(f'artist:"{artist}" track:"{title}"')
    if kind == "album" and artist:
        tries.append(f'artist:"{artist}" album:"{title}"')
    tries.append(text)

    rows = []
    for query in tries:
        path = "search" if kind == "track" else f"search/{kind}"
        try:
            rows = (client.get(path, q=query, limit=limit) or {}).get("data", [])
        except DeezerError:
            rows = []
        if rows:
            break
    if kind == "track" and not allow_unplayable:
        rows = [r for r in rows if r.get("readable", True)]
    for row in rows:
        row["confidence"] = round(confidence(row, artist, title, kind), 3)
    rows.sort(key=lambda r: (r["confidence"], r.get("rank") or 0), reverse=True)
    return rows


def by_isrc(client, code):
    """An ISRC identifies a recording exactly — no scoring needed."""
    row = client.get(f"track/isrc:{code}")
    row["confidence"] = 1.0
    return [row]


def resolve(client, text, kind="track", allow_unplayable=False):
    """The single best candidate, or None."""
    if kind == "track" and ISRC.match(text.strip()):
        try:
            return by_isrc(client, text.strip())[0]
        except DeezerError:
            return None
    rows = search(client, text, kind, 25, allow_unplayable)
    return rows[0] if rows else None


def emit(rows, kind, header=True):
    fields = FIELDS[kind] + ["confidence"]
    if header:
        print("#" + "\t".join(fields))
    for row in rows:
        values = []
        for f in fields:
            value = row
            for part in f.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            values.append(cell(value))
        print("\t".join(values))


def batch(client, source, kind, allow_unplayable, floor):
    """Resolve a list of queries. Unmatched lines keep their place."""
    lines = (sys.stdin.read() if source == "-"
             else Path(source).read_text()).splitlines()
    print("#query\tid\ttitle\tartist\tconfidence")
    misses = tried = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tried += 1
        row = resolve(client, line, kind, allow_unplayable)
        if not row or row["confidence"] < floor:
            misses += 1
            got = "" if not row else f"{row.get('title')} — " \
                                     f"{(row.get('artist') or {}).get('name')}"
            print(f"{cell(line)}\t\t{cell(got)}\t\t"
                  f"{row['confidence'] if row else 0}")
            continue
        print(f"{cell(line)}\t{row['id']}\t{cell(row.get('title'))}\t"
              f"{cell((row.get('artist') or {}).get('name'))}\t"
              f"{row['confidence']}")
    if misses:
        print(f"{misses} of {tried} lines did not resolve above "
              f"{floor} — check them by hand", file=sys.stderr)
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("query", nargs="?", help="free text, or an ISRC")
    p.add_argument("--kind", default="track", choices=KINDS)
    p.add_argument("--list", action="store_true", help="show all candidates")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--id-only", action="store_true")
    p.add_argument("--any", action="store_true",
                   help="keep tracks this account cannot play")
    p.add_argument("--batch", metavar="FILE", help="one query per line, - for stdin")
    p.add_argument("--min", type=float, default=FLOOR, dest="floor",
                   help=f"confidence floor for --batch (default {FLOOR})")
    args = p.parse_args()

    client = Deezer()
    if args.batch:
        return batch(client, args.batch, args.kind, args.any, args.floor)
    if not args.query:
        p.error("give a query or --batch")

    try:
        if args.kind == "track" and ISRC.match(args.query.strip()):
            rows = by_isrc(client, args.query.strip())
        else:
            rows = search(client, args.query, args.kind, max(args.limit, 25),
                          args.any)
    except DeezerError as e:
        print(f"deezer: {e}", file=sys.stderr)
        return 1
    if not rows:
        print(f"nothing found for {args.query!r}", file=sys.stderr)
        return 1

    if args.id_only:
        print(rows[0]["id"])
        return 0
    emit(rows[:args.limit] if args.list else rows[:1], args.kind)
    if not args.list and rows[0]["confidence"] < FLOOR:
        print(f"low confidence ({rows[0]['confidence']}) — run with --list "
              f"and confirm before writing this anywhere", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
