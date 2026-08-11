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
from dz_gw import Gw, GwError, as_playlist, as_track

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache" / "library.json"
SNAPSHOTS = ROOT / "snapshots"


def pull(gw, with_tracks=True):
    """Walk the account and return one dictionary describing all of it."""
    me = gw.user_id
    print(f"pulling {gw.name} (id {me})", file=sys.stderr)

    playlists = [as_playlist(row, me) for row in gw.profile_tab("playlists")]
    print(f"{len(playlists)} playlists "
          f"({sum(1 for p in playlists if p['mine'])} owned)", file=sys.stderr)

    if with_tracks:
        for n, entry in enumerate(playlists, 1):
            print(f"  [{n}/{len(playlists)}] {entry['title']} "
                  f"({entry['nb_tracks']})", file=sys.stderr)
            try:
                rows = gw.paginate("playlist.getSongs",
                                   PLAYLIST_ID=entry["id"])
            except GwError as e:
                print(f"    skipped: {e}", file=sys.stderr)
                entry["error"] = str(e)
                continue
            entry["tracks"] = [as_track(r) for r in rows]

    # The favourite tracks are a playlist, so they are already above when the
    # loved list belongs to this account. Pull them by id to be certain.
    favorites = {"tracks": [], "albums": [], "artists": []}
    try:
        favorites["tracks"] = [as_track(r) for r in gw.paginate(
            "playlist.getSongs", PLAYLIST_ID=gw.loved_playlist_id)]
    except GwError as e:
        print(f"favourite tracks: {e}", file=sys.stderr)
    for kind, tab, id_key, title_key in (
            ("albums", "albums", "ALB_ID", "ALB_TITLE"),
            ("artists", "artists", "ART_ID", "ART_NAME")):
        try:
            favorites[kind] = [{"id": row.get(id_key),
                                "title": row.get(title_key),
                                "artist": row.get("ART_NAME"),
                                "nb_tracks": row.get("NUMBER_TRACK")}
                               for row in gw.profile_tab(tab)]
        except GwError as e:
            print(f"favourite {kind}: {e}", file=sys.stderr)
    for kind in favorites:
        print(f"favourite {kind}: {len(favorites[kind])}", file=sys.stderr)

    return {"pulled": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "profile": {"id": me, "name": gw.name,
                        "country": gw.user.get("RECOMMENDATION_COUNTRY"),
                        "loved_playlist_id": gw.loved_playlist_id},
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
        library = pull(Gw(), with_tracks=not args.no_tracks)
    except GwError as e:
        print(f"deezer: {e}", file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else CACHE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(library, indent=1, ensure_ascii=False))
    total = sum(len(e["tracks"]) for e in library["playlists"])
    print(f"wrote {out} — {len(library['playlists'])} playlists, "
          f"{total} playlist tracks, "
          f"{len(library['favorites']['tracks'])} favourite tracks")

    if args.snapshot:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d-%H%M%S")
        keep = SNAPSHOTS / f"{stamp}.json"
        keep.write_text(json.dumps(library, indent=1, ensure_ascii=False))
        print(f"restore point: {keep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
