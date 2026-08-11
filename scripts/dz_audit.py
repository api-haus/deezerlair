#!/usr/bin/env python3
"""Report what is wrong with the library, and the command that repairs it.

    python3 scripts/dz_pull.py          # first, fill the cache
    python3 scripts/dz_audit.py         # then read the report
    python3 scripts/dz_audit.py --only overlap --json

Checks:
    summary     size of the library, and how much of it repeats
    duplicates  the same track, or the same song, twice in one playlist
    overlap     playlist pairs where one nearly contains the other
    dead        tracks this account can no longer play
    thin        empty and near-empty playlists
    twins       playlists whose titles say they are the same list
    artists     who dominates the library

Reads cache/library.json only — it never calls the API, so run it as often as
you like. Nothing here changes anything; each finding prints the command that
would.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dz_find import norm
from dz_pull import load

THIN = 5            # a playlist this small is probably an accident
OVERLAP = 0.8       # containment above this means "one is inside the other"
OVERLAP_MIN = 3     # below this, containment is coincidence, not a copy
CHECKS = ("summary", "duplicates", "overlap", "dead", "thin", "twins",
          "artists")


def song(track):
    return norm(track.get("artist")), norm(track.get("title"))


def mine(library):
    """Only the playlists this account owns — the rest cannot be edited."""
    return [p for p in library["playlists"] if p.get("mine")]


def check_summary(library, out):
    lists = mine(library)
    followed = len(library["playlists"]) - len(lists)
    all_tracks = [t for p in lists for t in p["tracks"]]
    unique = {t["id"] for t in all_tracks}
    songs = {song(t) for t in all_tracks}
    out.append(f"## summary\n"
               f"  {len(lists)} own playlists, {followed} followed\n"
               f"  {len(all_tracks)} playlist entries, {len(unique)} distinct "
               f"tracks, {len(songs)} distinct songs\n"
               f"  {len(library['favorites']['tracks'])} favourite tracks, "
               f"{len(library['favorites']['albums'])} albums, "
               f"{len(library['favorites']['artists'])} artists")
    return {"playlists": len(lists), "followed": followed,
            "entries": len(all_tracks), "tracks": len(unique),
            "songs": len(songs)}


def check_duplicates(library, out):
    found = []
    for p in mine(library):
        ids = Counter(t["id"] for t in p["tracks"])
        exact = sum(n - 1 for n in ids.values() if n > 1)
        by_song = Counter(song(t) for t in p["tracks"] if any(song(t)))
        loose = sum(n - 1 for n in by_song.values() if n > 1) - exact
        if exact or loose > 0:
            found.append({"id": p["id"], "title": p["title"],
                          "exact": exact, "loose": max(loose, 0)})
    found.sort(key=lambda f: f["exact"] + f["loose"], reverse=True)
    if found:
        out.append("## duplicates")
        for f in found:
            out.append(f"  {f['id']}  {f['title'][:44]:<44} "
                       f"{f['exact']} exact, {f['loose']} loose")
            out.append(f"      python3 scripts/dz_playlist.py dedupe "
                       f"{f['id']} --loose --apply")
    return found


def check_overlap(library, out):
    lists = [p for p in mine(library) if len(p["tracks"]) >= OVERLAP_MIN]
    sets = {p["id"]: {t["id"] for t in p["tracks"]} for p in lists}
    titles = {p["id"]: p["title"] for p in lists}
    found = []
    for a, b in combinations(sets, 2):
        shared = len(sets[a] & sets[b])
        if not shared:
            continue
        containment = shared / min(len(sets[a]), len(sets[b]))
        if containment >= OVERLAP:
            small, big = ((a, b) if len(sets[a]) <= len(sets[b]) else (b, a))
            found.append({"small": small, "big": big, "shared": shared,
                          "containment": round(containment, 2),
                          "small_title": titles[small],
                          "big_title": titles[big],
                          "small_size": len(sets[small]),
                          "big_size": len(sets[big])})
    found.sort(key=lambda f: f["containment"], reverse=True)
    if found:
        out.append("## overlap")
        for f in found:
            out.append(f"  {int(f['containment'] * 100)}% of "
                       f"{f['small']} {f['small_title'][:30]!r} "
                       f"({f['small_size']}) is inside "
                       f"{f['big']} {f['big_title'][:30]!r} ({f['big_size']})")
            out.append(f"      python3 scripts/dz_playlist.py merge "
                       f"{f['small']} --into {f['big']} --apply")
    return found


def check_dead(library, out):
    found = []
    for p in mine(library):
        gone = [t for t in p["tracks"] if not t.get("readable", True)]
        if gone:
            found.append({"id": p["id"], "title": p["title"],
                          "tracks": [{"id": t["id"], "title": t["title"],
                                      "artist": t["artist"]} for t in gone]})
    if found:
        out.append("## dead — cannot be played by this account")
        for f in found:
            out.append(f"  {f['id']}  {f['title'][:44]:<44} "
                       f"{len(f['tracks'])} dead")
            for t in f["tracks"][:5]:
                out.append(f"      {t['id']}  {t['artist']} — {t['title']}")
            if len(f["tracks"]) > 5:
                out.append(f"      ... and {len(f['tracks']) - 5} more")
            out.append(f"      python3 scripts/dz_playlist.py rm {f['id']} "
                       + " ".join(str(t["id"]) for t in f["tracks"][:20]))
    return found


def check_thin(library, out):
    found = [{"id": p["id"], "title": p["title"], "size": len(p["tracks"])}
             for p in mine(library)
             if len(p["tracks"]) < THIN and not p.get("is_loved_track")]
    found.sort(key=lambda f: f["size"])
    if found:
        out.append("## thin")
        for f in found:
            out.append(f"  {f['id']}  {f['title'][:44]:<44} {f['size']} "
                       f"track{'' if f['size'] == 1 else 's'}")
        out.append("      merge them somewhere, or: "
                   "python3 scripts/dz_playlist.py delete <id> --yes")
    return found


def check_twins(library, out):
    groups = defaultdict(list)
    for p in mine(library):
        stem = norm(p["title"])
        for filler in ("liked", "songs", "from", "spotify", "apple", "music",
                       "youtube", "tidal", "my", "playlist", "copy", "of",
                       "imported", "import", "new"):
            stem = " ".join(w for w in stem.split() if w != filler)
        # A title made of nothing but transfer words describes no list at all,
        # so all of those belong in one group.
        groups[stem or "(transfer words only)"].append(p)
    found = [{"stem": stem,
              "playlists": [{"id": p["id"], "title": p["title"],
                             "size": len(p["tracks"])} for p in group]}
             for stem, group in groups.items() if len(group) > 1]
    if found:
        out.append("## twins — titles that describe the same list")
        for f in found:
            out.append(f"  {f['stem'] or '(no distinct words)'}")
            for p in f["playlists"]:
                out.append(f"      {p['id']}  {p['title'][:40]:<40} "
                           f"{p['size']} tracks")
    return found


def check_artists(library, out):
    # Two playlists imported from two services spell the same artist two ways,
    # so count on the folded name and show the spelling used most often.
    counter, spellings = Counter(), defaultdict(Counter)
    for p in mine(library):
        for t in p["tracks"]:
            if t.get("artist"):
                counter[norm(t["artist"])] += 1
                spellings[norm(t["artist"])][t["artist"]] += 1
    top = [(spellings[folded].most_common(1)[0][0], n)
           for folded, n in counter.most_common(20)]
    if top:
        out.append("## artists — most present across own playlists")
        for name, n in top:
            out.append(f"  {n:>5}  {name}")
    return [{"artist": name, "entries": n} for name, n in top]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", choices=CHECKS, action="append")
    p.add_argument("--json", action="store_true")
    p.add_argument("--from", dest="source", metavar="FILE")
    args = p.parse_args()

    library = load(args.source)
    if not any(p["tracks"] for p in library["playlists"]):
        print("this cache has no tracks — pull again without --no-tracks",
              file=sys.stderr)
    lines, report = [], {}
    for name in (args.only or CHECKS):
        report[name] = globals()[f"check_{name}"](library, lines)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    print(f"# library of {library['profile'].get('name')}, "
          f"pulled {library['pulled']}\n")
    print("\n".join(lines) if lines else "nothing to report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
