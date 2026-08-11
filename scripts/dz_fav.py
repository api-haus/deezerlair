#!/usr/bin/env python3
"""Read and change the favourites — tracks, albums and artists.

    dz_fav.py list tracks                        also: albums, artists
    dz_fav.py add tracks 3135556 916424
    dz_fav.py add tracks --query "Air - La Femme d'Argent"
    dz_fav.py add artists --query "Boards of Canada"
    dz_fav.py add tracks --resolve wanted.txt    one "Artist - Title" a line
    dz_fav.py rm tracks 3135556
    dz_fav.py has tracks 3135556                 is it a favourite already

Deezer takes one id per call here, so a long list costs a call per item and
the pacing in dz_gw.py keeps it civil. `add` reads the current favourites
first and skips whatever is already there.

The favourite tracks are the same list as the "Loved Tracks" playlist. Manage
them here, not with dz_playlist.py.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dz import Deezer, cell
from dz_find import resolve
from dz_gw import Gw, GwError, as_track

# kind -> (add method, remove method, id parameter, search kind)
WRITE = {
    "tracks": ("favorite_song.add", "favorite_song.remove", "SNG_ID", "track"),
    "albums": ("album.addFavorite", "album.deleteFavorite", "ALB_ID", "album"),
    "artists": ("artist.addFavorite", "artist.deleteFavorite", "ART_ID",
                "artist"),
}


def current(gw, kind):
    """The ids already favourited, as strings."""
    if kind == "tracks":
        return {str(t["id"]) for t in
                (as_track(r) for r in gw.paginate(
                    "playlist.getSongs", PLAYLIST_ID=gw.loved_playlist_id))}
    id_key = "ALB_ID" if kind == "albums" else "ART_ID"
    return {str(r.get(id_key)) for r in gw.profile_tab(kind)}


def gather(gw, args):
    """Ids from the positional list, from files, and from resolved queries."""
    ids = []
    for raw in args.ids:
        if raw == "-":
            ids += [l.strip() for l in sys.stdin if l.strip()]
        else:
            ids.append(raw)
    queries = list(args.query or [])
    if args.resolve:
        text = (sys.stdin.read() if args.resolve == "-"
                else Path(args.resolve).read_text())
        queries += [l.strip() for l in text.splitlines()
                    if l.strip() and not l.startswith("#")]
    if queries:
        catalogue = Deezer()                    # search needs no session
        find_kind = WRITE[args.kind][3]
        for query in queries:
            row = resolve(catalogue, query, kind=find_kind)
            if not row or row["confidence"] < args.floor:
                print(f"unresolved: {query!r} "
                      f"({row['confidence'] if row else 0})", file=sys.stderr)
                continue
            print(f"{query!r} -> {row['id']} "
                  f"{row.get('title') or row.get('name')}", file=sys.stderr)
            ids.append(str(row["id"]))
    seen, out = set(), []
    for i in ids:
        if str(i).isdigit() and i not in seen:
            seen.add(i)
            out.append(str(i))
    return out


def cmd_list(gw, args):
    if args.kind == "tracks":
        rows = [as_track(r) for r in gw.paginate(
            "playlist.getSongs", PLAYLIST_ID=gw.loved_playlist_id)]
        print("#id\ttitle\tartist\talbum\treadable\tlossless")
        for t in rows:
            print("\t".join(cell(v) for v in (
                t["id"], t["title"], t["artist"], t["album"], t["readable"],
                t["lossless"])))
        return 0
    rows = gw.profile_tab(args.kind)
    if args.kind == "albums":
        print("#id\ttitle\tartist\tnb_tracks")
        for r in rows:
            print("\t".join(cell(v) for v in (
                r.get("ALB_ID"), r.get("ALB_TITLE"), r.get("ART_NAME"),
                r.get("NUMBER_TRACK"))))
    else:
        print("#id\tname\tnb_fan")
        for r in rows:
            print("\t".join(cell(v) for v in (
                r.get("ART_ID"), r.get("ART_NAME"), r.get("NB_FAN"))))
    return 0


def cmd_add(gw, args):
    method, _, param, _ = WRITE[args.kind]
    ids = gather(gw, args)
    if not ids:
        print("nothing to add", file=sys.stderr)
        return 1
    have = current(gw, args.kind)
    fresh = [i for i in ids if i not in have]
    if len(ids) - len(fresh):
        print(f"{len(ids) - len(fresh)} already favourites, skipping them",
              file=sys.stderr)
    for i in fresh:
        gw.call(method, **{param: int(i)})
    print(f"added {len(fresh)} {args.kind} to favourites")
    return 0


def cmd_rm(gw, args):
    _, method, param, _ = WRITE[args.kind]
    ids = gather(gw, args)
    if not ids:
        print("nothing to remove", file=sys.stderr)
        return 1
    if not args.yes:
        have = current(gw, args.kind)
        for i in ids:
            print(f"would remove {i}" + ("" if i in have
                                         else "  (not a favourite anyway)"))
        print(f"\nwould remove {len(ids)} {args.kind} — pass --yes")
        return 0
    for i in ids:
        gw.call(method, **{param: int(i)})
    print(f"removed {len(ids)} {args.kind} from favourites")
    return 0


def cmd_has(gw, args):
    ids = gather(gw, args)
    have = current(gw, args.kind)
    for i in ids:
        print(f"{i}\t{'yes' if i in have else 'no'}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("list", "add", "rm", "has"):
        sp = sub.add_parser(name)
        sp.add_argument("kind", choices=sorted(WRITE))
        if name != "list":
            sp.add_argument("ids", nargs="*", help="ids, or - for stdin")
            sp.add_argument("--query", action="append", metavar="TEXT")
            sp.add_argument("--resolve", metavar="FILE",
                            help="free text, one query a line")
            sp.add_argument("--min", type=float, default=0.6, dest="floor")
        if name == "rm":
            sp.add_argument("--yes", action="store_true")
    args = p.parse_args()
    try:
        return globals()[f"cmd_{args.cmd}"](Gw(), args)
    except GwError as e:
        print(f"deezer: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
