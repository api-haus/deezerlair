#!/usr/bin/env python3
"""Create, fill, tidy and merge playlists.

    dz_playlist.py list                          every playlist, as TSV
    dz_playlist.py show 12345                    its tracks, as TSV
    dz_playlist.py create "Title" [--private] [--description TEXT]
    dz_playlist.py add 12345 3135556 916424      by track id
    dz_playlist.py add 12345 --query "Air - La Femme d'Argent"
    dz_playlist.py add 12345 --resolve list.txt  one "Artist - Title" a line
    dz_playlist.py add 12345 --from-file ids.txt
    dz_playlist.py rm 12345 3135556
    dz_playlist.py rename 12345 "Better Title"
    dz_playlist.py describe 12345 "what this is for"
    dz_playlist.py dedupe 12345 [--loose] [--apply]
    dz_playlist.py merge 111 222 --into 333 [--apply] [--drop-sources]
    dz_playlist.py sort 12345 --by artist [--apply]
    dz_playlist.py export 12345                  "Artist - Title" lines
    dz_playlist.py delete 12345 --yes

Anything that changes the account prints a plan and stops. Pass --apply (or
--yes for delete) to carry it out. Take a restore point first:

    python3 scripts/dz_pull.py --snapshot

Deezer removes *every* copy of a track id when you delete it from a playlist,
so `dedupe` deletes the id and adds it back once — the surviving copy moves to
the end of the playlist. Loose duplicates are different ids, so they just go.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dz import Deezer, DeezerError, cell
from dz_find import norm, resolve

CHUNK = 50          # track ids per write call, to keep the URL sane
ORDER_MAX = 400     # a longer order= list overflows the request line


def chunked(items, size=CHUNK):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def playlist(client, pid):
    return client.get(f"playlist/{pid}")


def tracks(client, pid):
    return client.paginate(f"playlist/{pid}/tracks")


def key(track):
    """The identity of a song across releases: artist plus title, folded."""
    return norm((track.get("artist") or {}).get("name")), norm(track.get("title"))


def collect(client, args):
    """Every track id the caller asked for, from ids, files and queries."""
    ids = []
    for raw in args.ids:
        if raw == "-":
            ids += [l.strip() for l in sys.stdin if l.strip()]
        else:
            ids.append(raw)
    if args.from_file:
        for line in Path(args.from_file).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                ids.append(line.split("\t")[0])
    for query in args.query or []:
        row = resolve(client, query)
        if not row or row["confidence"] < args.floor:
            print(f"unresolved: {query!r} "
                  f"({row['confidence'] if row else 0})", file=sys.stderr)
            continue
        print(f"{query!r} -> {row['id']} {row.get('title')} — "
              f"{(row.get('artist') or {}).get('name')}", file=sys.stderr)
        ids.append(str(row["id"]))
    if args.resolve:
        lines = (sys.stdin.read() if args.resolve == "-"
                 else Path(args.resolve).read_text()).splitlines()
        misses = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            row = resolve(client, line)
            if not row or row["confidence"] < args.floor:
                misses.append(line)
                continue
            ids.append(str(row["id"]))
        if misses:
            print(f"{len(misses)} lines did not resolve:", file=sys.stderr)
            for line in misses:
                print(f"  {line}", file=sys.stderr)
    seen, out = set(), []
    for i in ids:
        if i.isdigit() and i not in seen:
            seen.add(i)
            out.append(i)
    return out


# -- read ------------------------------------------------------------------

def cmd_list(client, args):
    rows = client.paginate("user/me/playlists")
    me = client.me().get("id")
    print("#id\ttitle\tnb_tracks\tmine\tpublic\tloved\tcreator")
    for r in rows:
        creator = (r.get("creator") or {})
        print("\t".join(cell(v) for v in (
            r.get("id"), r.get("title"), r.get("nb_tracks"),
            creator.get("id") == me, r.get("public"),
            r.get("is_loved_track", False), creator.get("name"))))
    return 0


def cmd_show(client, args):
    rows = tracks(client, args.playlist)
    print("#id\ttitle\tartist\talbum\tduration\treadable")
    for t in rows:
        print("\t".join(cell(v) for v in (
            t.get("id"), t.get("title"), (t.get("artist") or {}).get("name"),
            (t.get("album") or {}).get("title"), t.get("duration"),
            t.get("readable", True))))
    return 0


def cmd_export(client, args):
    for t in tracks(client, args.playlist):
        print(f"{(t.get('artist') or {}).get('name')} - {t.get('title')}")
    return 0


# -- write -----------------------------------------------------------------

def cmd_create(client, args):
    made = client.post("user/me/playlists", title=args.title)
    pid = made.get("id") if isinstance(made, dict) else made
    fields = {}
    if args.description:
        fields["description"] = args.description
    if args.private:
        fields["public"] = "false"
    if fields:
        client.post(f"playlist/{pid}", **fields)
    print(f"created playlist {pid}: {args.title}")
    return 0


def cmd_add(client, args):
    ids = collect(client, args)
    if not ids:
        print("nothing to add", file=sys.stderr)
        return 1
    head = playlist(client, args.playlist)
    existing = {str(t["id"]) for t in tracks(client, args.playlist)}
    fresh = [i for i in ids if i not in existing]
    dupes = len(ids) - len(fresh)
    if dupes:
        print(f"{dupes} already in the playlist, skipping them",
              file=sys.stderr)
    if not fresh:
        print("every track is already there")
        return 0
    for part in chunked(fresh):
        client.post(f"playlist/{args.playlist}/tracks", songs=",".join(part))
    print(f"added {len(fresh)} tracks to {args.playlist} ({head.get('title')})")
    return 0


def cmd_rm(client, args):
    ids = collect(client, args)
    if not ids:
        print("nothing to remove", file=sys.stderr)
        return 1
    for part in chunked(ids):
        client.delete(f"playlist/{args.playlist}/tracks", songs=",".join(part))
    print(f"removed {len(ids)} tracks from {args.playlist}")
    return 0


def cmd_rename(client, args):
    client.post(f"playlist/{args.playlist}", title=args.title)
    print(f"playlist {args.playlist} is now {args.title!r}")
    return 0


def cmd_describe(client, args):
    client.post(f"playlist/{args.playlist}", description=args.text)
    print(f"described playlist {args.playlist}")
    return 0


def cmd_delete(client, args):
    head = playlist(client, args.playlist)
    if not args.yes:
        print(f"would delete {args.playlist}: {head.get('title')} "
              f"({head.get('nb_tracks')} tracks) — pass --yes")
        return 0
    client.delete(f"playlist/{args.playlist}")
    print(f"deleted {args.playlist}: {head.get('title')}")
    return 0


def cmd_dedupe(client, args):
    rows = tracks(client, args.playlist)
    seen, exact, loose = {}, [], []
    for pos, t in enumerate(rows):
        tid = str(t["id"])
        if tid in seen:
            exact.append((tid, t))
        else:
            seen[tid] = pos
    if args.loose:
        by_song = {}
        for t in rows:
            song = key(t)
            if not any(song):
                continue
            if song in by_song and str(t["id"]) != str(by_song[song]["id"]):
                loose.append((t, by_song[song]))
            else:
                by_song.setdefault(song, t)

    doomed = {tid for tid, _ in exact}
    for t, kept in loose:
        doomed.add(str(t["id"]))
    if not exact and not loose:
        print("no duplicates")
        return 0
    for tid, t in exact:
        print(f"exact  {tid}\t{t.get('title')} — "
              f"{(t.get('artist') or {}).get('name')}")
    for t, kept in loose:
        print(f"loose  {t['id']}\t{t.get('title')} — "
              f"{(t.get('artist') or {}).get('name')}  "
              f"(keeping {kept['id']} "
              f"{(kept.get('album') or {}).get('title', '')})")
    if not args.apply:
        print(f"\nwould drop {len(exact)} exact and {len(loose)} loose "
              f"duplicates — pass --apply")
        return 0

    for part in chunked(sorted(doomed)):
        client.delete(f"playlist/{args.playlist}/tracks", songs=",".join(part))
    # An exact duplicate loses every copy above, so put one copy back.
    back = sorted({tid for tid, _ in exact})
    for part in chunked(back):
        client.post(f"playlist/{args.playlist}/tracks", songs=",".join(part))
    print(f"dropped {len(exact)} exact and {len(loose)} loose duplicates"
          + (f"; {len(back)} tracks moved to the end" if back else ""))
    return 0


def cmd_merge(client, args):
    target = playlist(client, args.into)
    have = {str(t["id"]) for t in tracks(client, args.into)}
    incoming, sources = [], []
    for pid in args.sources:
        head = playlist(client, pid)
        rows = tracks(client, pid)
        sources.append((pid, head.get("title"), len(rows)))
        for t in rows:
            tid = str(t["id"])
            if tid not in have:
                have.add(tid)
                incoming.append(tid)
    for pid, title, count in sources:
        print(f"source {pid}: {title} ({count} tracks)")
    print(f"target {args.into}: {target.get('title')} "
          f"({target.get('nb_tracks')} tracks)")
    print(f"{len(incoming)} tracks are new to the target")
    if not args.apply:
        print("pass --apply to merge")
        return 0
    for part in chunked(incoming):
        client.post(f"playlist/{args.into}/tracks", songs=",".join(part))
    print(f"merged {len(incoming)} tracks into {args.into}")
    if args.drop_sources:
        for pid, title, _ in sources:
            client.delete(f"playlist/{pid}")
            print(f"deleted source {pid}: {title}")
    return 0


SORTS = {
    "artist": lambda t: (norm((t.get("artist") or {}).get("name")),
                         norm((t.get("album") or {}).get("title")),
                         norm(t.get("title"))),
    "album": lambda t: (norm((t.get("album") or {}).get("title")),
                        norm(t.get("title"))),
    "title": lambda t: norm(t.get("title")),
    "duration": lambda t: t.get("duration") or 0,
}


def cmd_sort(client, args):
    rows = tracks(client, args.playlist)
    if len(rows) > ORDER_MAX:
        sys.exit(f"{len(rows)} tracks is past the {ORDER_MAX} that fit in one "
                 f"order request — split the playlist first")
    order = sorted(rows, key=SORTS[args.by])
    if [t["id"] for t in order] == [t["id"] for t in rows]:
        print(f"already sorted by {args.by}")
        return 0
    for t in order[:12]:
        print(f"{t['id']}\t{(t.get('artist') or {}).get('name')} — "
              f"{t.get('title')}")
    if len(order) > 12:
        print(f"... and {len(order) - 12} more")
    if not args.apply:
        print(f"\nwould reorder {len(order)} tracks by {args.by} — pass --apply")
        return 0
    client.post(f"playlist/{args.playlist}/tracks",
                order=",".join(str(t["id"]) for t in order))
    print(f"reordered {len(order)} tracks by {args.by}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_sources(sp):
        sp.add_argument("ids", nargs="*", help="track ids, or - for stdin")
        sp.add_argument("--from-file", metavar="FILE", help="ids, one a line")
        sp.add_argument("--resolve", metavar="FILE",
                        help="free text, one query a line")
        sp.add_argument("--query", action="append", metavar="TEXT")
        sp.add_argument("--min", type=float, default=0.6, dest="floor",
                        help="confidence floor when resolving (default 0.6)")

    sub.add_parser("list")
    for name in ("show", "export"):
        sp = sub.add_parser(name)
        sp.add_argument("playlist")

    sp = sub.add_parser("create")
    sp.add_argument("title")
    sp.add_argument("--description")
    sp.add_argument("--private", action="store_true")

    for name in ("add", "rm"):
        sp = sub.add_parser(name)
        sp.add_argument("playlist")
        with_sources(sp)

    sp = sub.add_parser("rename")
    sp.add_argument("playlist")
    sp.add_argument("title")

    sp = sub.add_parser("describe")
    sp.add_argument("playlist")
    sp.add_argument("text")

    sp = sub.add_parser("delete")
    sp.add_argument("playlist")
    sp.add_argument("--yes", action="store_true")

    sp = sub.add_parser("dedupe")
    sp.add_argument("playlist")
    sp.add_argument("--loose", action="store_true",
                    help="also drop the same song under a different id")
    sp.add_argument("--apply", action="store_true")

    sp = sub.add_parser("merge")
    sp.add_argument("sources", nargs="+")
    sp.add_argument("--into", required=True)
    sp.add_argument("--apply", action="store_true")
    sp.add_argument("--drop-sources", action="store_true")

    sp = sub.add_parser("sort")
    sp.add_argument("playlist")
    sp.add_argument("--by", default="artist", choices=sorted(SORTS))
    sp.add_argument("--apply", action="store_true")

    args = p.parse_args()
    client = Deezer()
    try:
        return globals()[f"cmd_{args.cmd}"](client, args)
    except DeezerError as e:
        print(f"deezer: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
