#!/usr/bin/env python3
"""Read and change the favourites — tracks, albums and artists.

    dz_fav.py list tracks                        also: albums, artists
    dz_fav.py add tracks 3135556 916424
    dz_fav.py add tracks --query "Air - La Femme d'Argent"
    dz_fav.py add artists --query "Boards of Canada"
    dz_fav.py add tracks --resolve wanted.txt    one "Artist - Title" a line
    dz_fav.py rm tracks 3135556
    dz_fav.py has tracks 3135556                 is it a favourite already

Deezer takes one id per call here, so a long list costs a call per track and
the pacing in dz.py keeps it inside the quota. Adding something twice is
harmless; `add` checks the current favourites first and skips what is there.

The favourite tracks are the same list as the "Loved Tracks" playlist. Do not
manage that playlist with dz_playlist.py — use this script.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dz import Deezer, DeezerError, cell
from dz_find import resolve

KINDS = {
    "tracks": ("track_id", "track", ["id", "title", "artist", "album"]),
    "albums": ("album_id", "album", ["id", "title", "artist", "nb_tracks"]),
    "artists": ("artist_id", "artist", ["id", "name", "nb_fan"]),
}


def row_cells(row, fields):
    out = []
    for f in fields:
        value = row.get(f)
        if isinstance(value, dict):
            value = value.get("name") or value.get("title")
        out.append(cell(value))
    return out


def current(client, kind):
    return {str(r["id"]) for r in client.paginate(f"user/me/{kind}")}


def gather(client, args):
    """Track/album/artist ids from the positional list, files and queries."""
    param, find_kind, _ = KINDS[args.kind]
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
    for query in queries:
        row = resolve(client, query, kind=find_kind)
        if not row or row["confidence"] < args.floor:
            print(f"unresolved: {query!r} "
                  f"({row['confidence'] if row else 0})", file=sys.stderr)
            continue
        label = row.get("title") or row.get("name")
        print(f"{query!r} -> {row['id']} {label}", file=sys.stderr)
        ids.append(str(row["id"]))
    seen, out = set(), []
    for i in ids:
        if i.isdigit() and i not in seen:
            seen.add(i)
            out.append(i)
    return param, out


def cmd_list(client, args):
    _, _, fields = KINDS[args.kind]
    rows = client.paginate(f"user/me/{args.kind}")
    print("#" + "\t".join(fields))
    for row in rows:
        print("\t".join(row_cells(row, fields)))
    return 0


def cmd_add(client, args):
    param, ids = gather(client, args)
    if not ids:
        print("nothing to add", file=sys.stderr)
        return 1
    have = current(client, args.kind)
    fresh = [i for i in ids if i not in have]
    if len(ids) - len(fresh):
        print(f"{len(ids) - len(fresh)} already favourites, skipping them",
              file=sys.stderr)
    for i in fresh:
        client.post(f"user/me/{args.kind}", **{param: i})
    print(f"added {len(fresh)} {args.kind} to favourites")
    return 0


def cmd_rm(client, args):
    param, ids = gather(client, args)
    if not ids:
        print("nothing to remove", file=sys.stderr)
        return 1
    for i in ids:
        client.delete(f"user/me/{args.kind}", **{param: i})
    print(f"removed {len(ids)} {args.kind} from favourites")
    return 0


def cmd_has(client, args):
    _, ids = gather(client, args)
    have = current(client, args.kind)
    for i in ids:
        print(f"{i}\t{'yes' if i in have else 'no'}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("list", "add", "rm", "has"):
        sp = sub.add_parser(name)
        sp.add_argument("kind", choices=sorted(KINDS))
        if name != "list":
            sp.add_argument("ids", nargs="*", help="ids, or - for stdin")
            sp.add_argument("--query", action="append", metavar="TEXT")
            sp.add_argument("--resolve", metavar="FILE",
                            help="free text, one query a line")
            sp.add_argument("--min", type=float, default=0.6, dest="floor")
    args = p.parse_args()
    client = Deezer()
    try:
        return globals()[f"cmd_{args.cmd}"](client, args)
    except DeezerError as e:
        print(f"deezer: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
