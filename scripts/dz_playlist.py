#!/usr/bin/env python3
"""Create, fill, tidy and merge playlists.

    dz_playlist.py list                          every playlist, as TSV
    dz_playlist.py show 12345                    its tracks, as TSV
    dz_playlist.py create "Title" [--public] [--description TEXT]
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
    dz_playlist.py privacy private --all [--apply]
    dz_playlist.py export 12345                  "Artist - Title" lines
    dz_playlist.py delete 12345 --yes

Anything that changes the account prints a plan and stops. Pass --apply (or
--yes for delete) to carry it out. Take a restore point first:

    python3 scripts/dz_pull.py --snapshot

Deezer refuses to hold the same track id twice in one playlist, so a duplicate
is always two *different* ids for one recording. `dedupe` matches them on ISRC
by default, which is the same recording beyond doubt; `--loose` also matches
on artist and title, which catches re-recordings and needs your eye. Of each
group it keeps the playable, lossless copy, and the earliest one on a tie.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dz import Deezer, cell
from dz_find import FLOOR, norm, resolve
from dz_gw import (STATUS_PRIVATE, STATUS_PUBLIC, Gw, GwError, as_playlist,
                   as_track, songs_payload)


def head(gw, pid):
    """Metadata for one playlist: title, description, status, owner."""
    data = (gw.call("deezer.pagePlaylist", playlist_id=int(pid), lang="en",
                    nb=1, start=0, tags=True, header=True) or {}).get("DATA")
    if not data:
        raise GwError(f"playlist {pid} not found")
    return data


def tracks(gw, pid):
    return [as_track(r) for r in gw.paginate("playlist.getSongs",
                                             PLAYLIST_ID=int(pid))]


def owned(gw, pid, action):
    """Refuse to write to a playlist this account does not own."""
    data = head(gw, pid)
    if str(data.get("PARENT_USER_ID")) != str(gw.user_id):
        sys.exit(f"playlist {pid} ({data.get('TITLE')}) belongs to user "
                 f"{data.get('PARENT_USER_ID')}, not to you — refusing to "
                 f"{action} it")
    return data


def key(track):
    """The identity of a song: its ISRC, else artist plus title, folded."""
    if track.get("isrc"):
        return ("isrc", track["isrc"])
    return ("song", norm(track.get("artist")), norm(track.get("title")))


def song_key(track):
    return "song", norm(track.get("artist")), norm(track.get("title"))


def collect(gw, args):
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
    queries = list(args.query or [])
    if args.resolve:
        text = (sys.stdin.read() if args.resolve == "-"
                else Path(args.resolve).read_text())
        queries += [l.strip() for l in text.splitlines()
                    if l.strip() and not l.startswith("#")]
    misses = []
    catalogue = Deezer() if queries else None    # search needs no session
    for query in queries:
        row = resolve(catalogue, query)
        if not row or row["confidence"] < args.floor:
            misses.append(query)
            continue
        print(f"{query!r} -> {row['id']} {row.get('title')} — "
              f"{(row.get('artist') or {}).get('name')}", file=sys.stderr)
        ids.append(str(row["id"]))
    if misses:
        print(f"{len(misses)} queries did not resolve above {args.floor}:",
              file=sys.stderr)
        for query in misses:
            print(f"  {query}", file=sys.stderr)
    seen, out = set(), []
    for i in ids:
        if str(i).isdigit() and i not in seen:
            seen.add(i)
            out.append(int(i))
    return out


# -- read ------------------------------------------------------------------

def cmd_list(gw, args):
    rows = [as_playlist(r, gw.user_id) for r in gw.profile_tab("playlists")]
    rows.sort(key=lambda p: (not p["mine"], -(p["nb_tracks"] or 0)))
    print("#id\ttitle\tnb_tracks\tmine\tpublic\tloved")
    for p in rows:
        print("\t".join(cell(v) for v in (
            p["id"], p["title"], p["nb_tracks"], p["mine"], p["public"],
            p["is_loved_track"])))
    return 0


def cmd_show(gw, args):
    rows = tracks(gw, args.playlist)
    print("#id\ttitle\tartist\talbum\tduration\treadable\tlossless\tisrc")
    for t in rows:
        print("\t".join(cell(v) for v in (
            t["id"], t["title"], t["artist"], t["album"], t["duration"],
            t["readable"], t["lossless"], t["isrc"])))
    return 0


def cmd_export(gw, args):
    for t in tracks(gw, args.playlist):
        print(f"{t['artist']} - {t['title']}")
    return 0


# -- write -----------------------------------------------------------------

def cmd_create(gw, args):
    status = STATUS_PUBLIC if args.public else STATUS_PRIVATE
    pid = gw.call("playlist.create", title=args.title, status=status,
                  description=args.description or "", songs=[])
    print(f"created playlist {pid}: {args.title} "
          f"({'public' if args.public else 'private'})")
    return 0


def cmd_add(gw, args):
    ids = collect(gw, args)
    if not ids:
        print("nothing to add", file=sys.stderr)
        return 1
    data = owned(gw, args.playlist, "add to")
    existing = {t["id"] for t in tracks(gw, args.playlist)}
    fresh = [i for i in ids if i not in existing]
    if len(ids) - len(fresh):
        print(f"{len(ids) - len(fresh)} already in the playlist, skipping",
              file=sys.stderr)
    if not fresh:
        print("every track is already there")
        return 0
    gw.call("playlist.addSongs", PLAYLIST_ID=int(args.playlist),
            songs=songs_payload(fresh), offset=-1)
    print(f"added {len(fresh)} tracks to {args.playlist} ({data.get('TITLE')})")
    return 0


def cmd_rm(gw, args):
    ids = collect(gw, args)
    if not ids:
        print("nothing to remove", file=sys.stderr)
        return 1
    owned(gw, args.playlist, "remove from")
    gw.call("playlist.deleteSongs", PLAYLIST_ID=int(args.playlist),
            songs=songs_payload(ids))
    print(f"removed {len(ids)} tracks from {args.playlist}")
    return 0


def update(gw, pid, **fields):
    """playlist.update replaces the header, so send what is not changing."""
    data = owned(gw, pid, "edit")
    payload = {"PLAYLIST_ID": int(pid),
               "title": data.get("TITLE") or "",
               "description": data.get("DESCRIPTION") or "",
               "status": int(data.get("STATUS") or STATUS_PRIVATE)}
    payload.update(fields)
    gw.call("playlist.update", **payload)
    return data


def cmd_rename(gw, args):
    update(gw, args.playlist, title=args.title)
    print(f"playlist {args.playlist} is now {args.title!r}")
    return 0


def cmd_describe(gw, args):
    update(gw, args.playlist, description=args.text)
    print(f"described playlist {args.playlist}")
    return 0


def cmd_delete(gw, args):
    data = owned(gw, args.playlist, "delete")
    if not args.yes:
        print(f"would delete {args.playlist}: {data.get('TITLE')} "
              f"({data.get('NB_SONG')} tracks) — pass --yes")
        return 0
    gw.call("playlist.delete", PLAYLIST_ID=int(args.playlist))
    print(f"deleted {args.playlist}: {data.get('TITLE')}")
    return 0


def better(a, b):
    """Which of two copies of one recording to keep."""
    for field in ("readable", "lossless"):
        if a.get(field) != b.get(field):
            return a if a.get(field) else b
    return a                                    # tie: the earlier one wins


def cmd_dedupe(gw, args):
    rows = tracks(gw, args.playlist)
    groups = {}
    for track in rows:
        for k in ([key(track)] + ([song_key(track)] if args.loose else [])):
            if k[0] == "song" and not any(k[1:]):
                continue
            groups.setdefault(k, []).append(track)

    doomed, plan = {}, []
    for k, members in groups.items():
        unique = {t["id"]: t for t in members}
        if len(unique) < 2:
            continue
        keep = None
        for track in unique.values():
            keep = track if keep is None else better(keep, track)
        for track in unique.values():
            if track["id"] != keep["id"] and track["id"] not in doomed:
                doomed[track["id"]] = (track, keep, k[0])
    for track, keep, how in doomed.values():
        plan.append(f"  {how:4} drop {track['id']}\t{track['artist']} — "
                    f"{track['title']}"
                    f"{'' if track['readable'] else ' [unplayable]'}"
                    f"{'' if track['lossless'] else ' [no flac]'}\n"
                    f"       keep {keep['id']}\t{keep['album']}")
    if not doomed:
        print("no duplicates")
        return 0
    print("\n".join(plan))
    if not args.apply:
        print(f"\nwould drop {len(doomed)} duplicates of "
              f"{len(rows)} tracks — pass --apply")
        return 0
    owned(gw, args.playlist, "dedupe")
    gw.call("playlist.deleteSongs", PLAYLIST_ID=int(args.playlist),
            songs=songs_payload(doomed))
    print(f"dropped {len(doomed)} duplicates")
    return 0


def cmd_merge(gw, args):
    target = head(gw, args.into)
    have = {t["id"] for t in tracks(gw, args.into)}
    incoming, sources = [], []
    for pid in args.sources:
        data = head(gw, pid)
        rows = tracks(gw, pid)
        sources.append((pid, data.get("TITLE"), len(rows),
                        str(data.get("PARENT_USER_ID")) == str(gw.user_id)))
        for t in rows:
            if t["id"] not in have:
                have.add(t["id"])
                incoming.append(t["id"])
    for pid, title, count, mine in sources:
        print(f"source {pid}: {title} ({count} tracks)"
              f"{'' if mine else '  [not yours — cannot be deleted]'}")
    print(f"target {args.into}: {target.get('TITLE')} "
          f"({target.get('NB_SONG')} tracks)")
    print(f"{len(incoming)} tracks are new to the target")
    if not args.apply:
        print("pass --apply to merge")
        return 0
    owned(gw, args.into, "merge into")
    if incoming:
        gw.call("playlist.addSongs", PLAYLIST_ID=int(args.into),
                songs=songs_payload(incoming), offset=-1)
    print(f"merged {len(incoming)} tracks into {args.into}")
    if args.drop_sources:
        for pid, title, _, mine in sources:
            if not mine:
                print(f"kept {pid}: {title} — not yours to delete")
                continue
            gw.call("playlist.delete", PLAYLIST_ID=int(pid))
            print(f"deleted source {pid}: {title}")
    return 0


def cmd_privacy(gw, args):
    """Make playlists private or public, one header rewrite at a time.

    Idempotent on purpose: it reads the current state every run and touches
    only what is still wrong, so an interrupted bulk change is resumed simply
    by running it again.
    """
    want_public = args.visibility == "public"
    rows = [as_playlist(r, gw.user_id) for r in gw.profile_tab("playlists")]
    if args.all:
        chosen = [p for p in rows
                  if p["mine"] and str(p["id"]) != str(gw.loved_playlist_id)]
    else:
        wanted = {str(i) for i in args.ids}
        chosen = [p for p in rows if str(p["id"]) in wanted]
        missing = wanted - {str(p["id"]) for p in chosen}
        if missing:
            sys.exit(f"not your playlists, or not found: {', '.join(missing)}")
        theirs = [p for p in chosen if not p["mine"]]
        if theirs:
            sys.exit("refusing — these belong to someone else: "
                     + ", ".join(str(p["id"]) for p in theirs))
    todo = [p for p in chosen if p["public"] != want_public]
    print(f"{len(chosen)} playlists selected, {len(chosen) - len(todo)} "
          f"already {args.visibility}, {len(todo)} to change")
    if not todo:
        return 0
    for p in todo[:10]:
        print(f"  {p['id']}  {p['title'][:50]}")
    if len(todo) > 10:
        print(f"  ... and {len(todo) - 10} more")
    if not args.apply:
        print(f"\nwould make {len(todo)} playlists {args.visibility} "
              f"— pass --apply")
        return 0

    status = STATUS_PUBLIC if want_public else STATUS_PRIVATE
    done, failed = 0, []
    for n, p in enumerate(todo, 1):
        try:
            # update() re-reads the header first, because playlist.update
            # replaces it wholesale and would otherwise wipe the description.
            update(gw, p["id"], status=status)
            done += 1
        except (GwError, SystemExit) as e:
            failed.append((p["id"], p["title"], str(e)))
            print(f"  [{n}/{len(todo)}] {p['title'][:40]}: FAILED {e}",
                  file=sys.stderr)
            continue
        print(f"  [{n}/{len(todo)}] {p['title'][:50]}", file=sys.stderr)
    print(f"made {done} playlists {args.visibility}"
          + (f", {len(failed)} failed" if failed else ""))
    for pid, title, why in failed:
        print(f"  failed {pid} {title}: {why}", file=sys.stderr)
    if failed:
        print("re-run the same command to retry only what is still wrong",
              file=sys.stderr)
        return 1
    return 0


SORTS = {
    "artist": lambda t: (norm(t["artist"]), norm(t["album"]), norm(t["title"])),
    "album": lambda t: (norm(t["album"]), norm(t["title"])),
    "title": lambda t: norm(t["title"]),
    "duration": lambda t: t["duration"] or 0,
    "added": lambda t: str(t.get("time_add") or ""),
}


def cmd_sort(gw, args):
    rows = tracks(gw, args.playlist)
    order = sorted(rows, key=SORTS[args.by])
    if [t["id"] for t in order] == [t["id"] for t in rows]:
        print(f"already sorted by {args.by}")
        return 0
    for t in order[:12]:
        print(f"{t['id']}\t{t['artist']} — {t['title']}")
    if len(order) > 12:
        print(f"... and {len(order) - 12} more")
    if not args.apply:
        print(f"\nwould reorder {len(order)} tracks by {args.by} — pass --apply")
        return 0
    owned(gw, args.playlist, "reorder")
    gw.call("playlist.updateOrder", PLAYLIST_ID=int(args.playlist),
            order=[str(t["id"]) for t in order])
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
        sp.add_argument("--min", type=float, default=FLOOR, dest="floor",
                        help=f"confidence floor when resolving (default {FLOOR})")

    sub.add_parser("list")
    for name in ("show", "export"):
        sp = sub.add_parser(name)
        sp.add_argument("playlist")

    sp = sub.add_parser("create")
    sp.add_argument("title")
    sp.add_argument("--description")
    sp.add_argument("--public", action="store_true",
                    help="visible to everyone; the default is private")

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
                    help="also match on artist and title, not only ISRC")
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

    sp = sub.add_parser("privacy")
    sp.add_argument("visibility", choices=("private", "public"))
    sp.add_argument("ids", nargs="*")
    sp.add_argument("--all", action="store_true",
                    help="every playlist this account owns")
    sp.add_argument("--apply", action="store_true")

    args = p.parse_args()
    try:
        return globals()[f"cmd_{args.cmd}"](Gw(), args)
    except GwError as e:
        print(f"deezer: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
