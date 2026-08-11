#!/usr/bin/env python3
"""Copy the whole library into cache/library.json — and into a restore point.

Usage:
    python3 scripts/dz_pull.py                 refresh the cache
    python3 scripts/dz_pull.py --snapshot      also archive a restore point
    python3 scripts/dz_pull.py --no-tracks     playlist headers only, fast
    python3 scripts/dz_pull.py --ids 12345     print that playlist's track ids
    python3 scripts/dz_pull.py --ids 12345 --from snapshots/<file>.json

Read the cache instead of the API whenever you are looking at the shape of the
library — it holds every playlist and every track in one file, so counting,
grouping and comparing cost nothing and leak no quota.

A snapshot is the undo for everything destructive in this repo. Take one
before any bulk write; --ids on that snapshot gives the exact track list back,
ready to feed to `dz_playlist.py add`.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dz import ROOT, Deezer, DeezerError

CACHE = ROOT / "cache" / "library.json"
SNAPSHOTS = ROOT / "snapshots"


def slim_track(row):
    """Keep the fields the housekeeping scripts actually read."""
    return {"id": row.get("id"),
            "title": row.get("title"),
            "artist": (row.get("artist") or {}).get("name"),
            "artist_id": (row.get("artist") or {}).get("id"),
            "album": (row.get("album") or {}).get("title"),
            "album_id": (row.get("album") or {}).get("id"),
            "duration": row.get("duration"),
            "readable": row.get("readable", True),
            "time_add": row.get("time_add")}


def pull(client, with_tracks=True):
    """Walk the account and return one dictionary describing all of it."""
    profile = client.me()
    me = profile.get("id")
    print(f"pulling {profile.get('name')} (id {me})", file=sys.stderr)

    playlists = []
    for row in client.paginate("user/me/playlists"):
        entry = {"id": row.get("id"),
                 "title": row.get("title"),
                 "nb_tracks": row.get("nb_tracks"),
                 "public": row.get("public"),
                 "collaborative": row.get("collaborative"),
                 "is_loved_track": row.get("is_loved_track", False),
                 "creation_date": row.get("creation_date"),
                 "link": row.get("link"),
                 "creator_id": (row.get("creator") or {}).get("id"),
                 "creator": (row.get("creator") or {}).get("name"),
                 "mine": (row.get("creator") or {}).get("id") == me,
                 "tracks": []}
        playlists.append(entry)
    print(f"{len(playlists)} playlists", file=sys.stderr)

    if with_tracks:
        for n, entry in enumerate(playlists, 1):
            print(f"  [{n}/{len(playlists)}] {entry['title']} "
                  f"({entry['nb_tracks']})", file=sys.stderr)
            try:
                rows = client.paginate(f"playlist/{entry['id']}/tracks")
            except DeezerError as e:
                print(f"    skipped: {e}", file=sys.stderr)
                entry["error"] = str(e)
                continue
            entry["tracks"] = [slim_track(r) for r in rows]

    favorites = {}
    for kind in ("tracks", "albums", "artists"):
        try:
            rows = client.paginate(f"user/me/{kind}")
        except DeezerError as e:
            print(f"favorite {kind}: {e}", file=sys.stderr)
            rows = []
        favorites[kind] = ([slim_track(r) for r in rows] if kind == "tracks"
                           else [{"id": r.get("id"),
                                  "title": r.get("title") or r.get("name"),
                                  "artist": (r.get("artist") or {}).get("name"),
                                  "nb_tracks": r.get("nb_tracks")}
                                 for r in rows])
        print(f"favorite {kind}: {len(favorites[kind])}", file=sys.stderr)

    return {"pulled": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "profile": {k: profile.get(k)
                        for k in ("id", "name", "country", "link")},
            "playlists": playlists,
            "favorites": favorites}


def load(path=None):
    """Read a cache or snapshot file, with a useful error when it is absent."""
    p = Path(path) if path else CACHE
    if not p.exists():
        sys.exit(f"{p} does not exist — run: python3 scripts/dz_pull.py")
    return json.loads(p.read_text())


def print_ids(library, playlist_id):
    """The track ids of one playlist, in order, one per line."""
    for entry in library["playlists"]:
        if str(entry["id"]) == str(playlist_id):
            for track in entry["tracks"]:
                print(track["id"])
            return 0
    sys.exit(f"playlist {playlist_id} is not in this file")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--snapshot", action="store_true",
                   help="also archive a timestamped restore point")
    p.add_argument("--no-tracks", action="store_true",
                   help="playlist headers only")
    p.add_argument("--ids", metavar="PLAYLIST_ID",
                   help="print stored track ids instead of pulling")
    p.add_argument("--from", dest="source", metavar="FILE",
                   help="read this file instead of cache/library.json")
    p.add_argument("--out", metavar="FILE")
    args = p.parse_args()

    if args.ids:
        return print_ids(load(args.source), args.ids)

    try:
        library = pull(Deezer(), with_tracks=not args.no_tracks)
    except DeezerError as e:
        print(f"deezer: {e}", file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else CACHE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(library, indent=1, ensure_ascii=False))
    total = sum(len(e["tracks"]) for e in library["playlists"])
    print(f"wrote {out} — {len(library['playlists'])} playlists, "
          f"{total} playlist tracks, "
          f"{len(library['favorites']['tracks'])} favorite tracks")

    if args.snapshot:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d-%H%M%S")
        keep = SNAPSHOTS / f"{stamp}.json"
        keep.write_text(json.dumps(library, indent=1, ensure_ascii=False))
        print(f"restore point: {keep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
