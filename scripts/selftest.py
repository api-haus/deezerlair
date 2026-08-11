#!/usr/bin/env python3
"""Offline checks for the parts that are easy to get quietly wrong.

    python3 scripts/selftest.py

Touches no network and no account, so it is safe to run at any time. It covers
the pure logic — query folding, match confidence, the throttle classifier and
its back-off, TSV projection, which copy of a duplicate survives — and it
holds `.agents/skills/` and `.claude/skills/` to being identical.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dz_gw
from dz import as_tsv, pluck
from dz_find import ISRC, norm, ratio, split_query
from dz_gw import Throttled, as_playlist, as_track, looks_throttled

FAILED = []


def check(label, got, want):
    if got != want:
        FAILED.append(f"{label}: got {got!r}, wanted {want!r}")


def check_true(label, got):
    if not got:
        FAILED.append(f"{label}: got {got!r}, wanted something truthy")


# -- query folding ---------------------------------------------------------
check("norm strips decoration",
      norm("Here Comes The Sun - Remastered 2009"), "here comes the sun")
check("norm strips a feature", norm("Umbrella (feat. Jay-Z)"), "umbrella")
check("norm folds accents and case", norm("Björk"), "bjork")
check("norm collapses punctuation", norm("Sgt. Pepper's!"), "sgt pepper s")
check("split on a dash", split_query("Boards of Canada - Roygbiv"),
      ("Boards of Canada", "Roygbiv"))
check("split on an en dash", split_query("Aphex Twin – Xtal"),
      ("Aphex Twin", "Xtal"))
check("split on by", split_query("Roygbiv by Boards of Canada"),
      ("Roygbiv", "Boards of Canada"))
check("no separator leaves a bare title", split_query("roygbiv"),
      ("", "roygbiv"))
check("identical strings score 1", ratio("Xtal", "xtal"), 1.0)
check("containment scores high", ratio("Xtal", "Xtal (Live)"), 1.0)
check_true("unrelated strings score low", ratio("Xtal", "Teardrop") < 0.4)
check_true("an ISRC is recognised", bool(ISRC.match("USUG11600976")))
check_true("a title is not an ISRC", not ISRC.match("Boards of Canada"))

# -- throttle classification ----------------------------------------------
check_true("quota error is a throttle",
           looks_throttled({"DATA_ERROR": "Quota limit exceeded"}))
check_true("too-many error is a throttle",
           looks_throttled({"REQUEST_ERROR": "Too many requests"}))
check_true("slow-down error is a throttle", looks_throttled("Slow down"))
check_true("a missing parameter is not a throttle",
           not looks_throttled({"MISSING_PARAMETER_TITLE": "missing"}))
check_true("a CSRF failure is not a throttle",
           not looks_throttled({"VALID_TOKEN_REQUIRED": "Invalid CSRF token"}))
check("Retry-After in seconds", dz_gw.retry_after_seconds({"Retry-After": "7"}),
      7.0)
check("no Retry-After header", dz_gw.retry_after_seconds({}), None)


# -- back-off actually backs off -------------------------------------------
class FakeGw(dz_gw.Gw):
    """A session that never opens a socket, to exercise the retry loop."""

    def __init__(self, failures):
        self.arl = "x" * 192
        self.token = "token"
        self.verbose = False
        self.source = "test"
        self._user = {"USER_ID": 1}
        self._calls = __import__("collections").deque()
        self.spacing = 0.0
        self.throttles = 0
        self._since_throttle = 0
        self._last_call = 0.0
        self.failures = failures
        self.attempts = 0

    def _post(self, method, payload):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise Throttled("HTTP 429", retry_after=0)   # 0 keeps the test fast
        return {"error": [], "results": "ok"}


gw = FakeGw(failures=2)
started = time.monotonic()
check("a throttled call still returns", gw.call("playlist.getSongs"), "ok")
check("it retried until it worked", gw.attempts, 3)
check("both throttles were counted", gw.throttles, 2)
check_true("pacing was widened", gw.spacing >= dz_gw.SPACING_FIRST)
check_true("the test did not actually sleep", time.monotonic() - started < 5)

gw = FakeGw(failures=99)
try:
    gw.call("playlist.getSongs")
    FAILED.append("endless throttling should have raised")
except dz_gw.GwError as e:
    check_true("it gives up eventually", "throttled" in str(e))
check("it gave up after the set number of waits",
      gw.attempts, dz_gw.THROTTLE_RETRIES + 1)

# -- shapes ----------------------------------------------------------------
track = as_track({"SNG_ID": "123", "SNG_TITLE": "Xtal", "VERSION": "(Live)",
                  "ART_NAME": "Aphex Twin", "ALB_TITLE": "SAW", "DURATION": "294",
                  "FILESIZE": "0", "FILESIZE_FLAC": "0", "ISRC": "BEZ350800022"})
check("the version is kept in the title", track["title"], "Xtal (Live)")
check("FILESIZE 0 means unplayable", track["readable"], False)
check("FILESIZE_FLAC 0 means no lossless", track["lossless"], False)
check("the id becomes a number", track["id"], 123)
playable = as_track({"SNG_ID": "1", "SNG_TITLE": "A", "FILESIZE": "5",
                     "FILESIZE_FLAC": "9", "DURATION": "1"})
check_true("a sized track is playable", playable["readable"])
check_true("a FLAC size means lossless", playable["lossless"])
check("a version already in the title is not repeated",
      as_track({"SNG_ID": "1", "SNG_TITLE": "B (Live)", "VERSION": "(Live)",
                "DURATION": "0"})["title"], "B (Live)")

public = as_playlist({"PLAYLIST_ID": "9", "TITLE": "T", "NB_SONG": 3,
                      "STATUS": 0, "PARENT_USER_ID": "7"}, me="7")
private = as_playlist({"PLAYLIST_ID": "9", "TITLE": "T", "NB_SONG": 3,
                       "STATUS": 1, "PARENT_USER_ID": "8"}, me="7")
check("STATUS 0 is public", public["public"], True)
check("STATUS 1 is private", private["public"], False)
check("my own playlist is mine", public["mine"], True)
check("another user's playlist is not", private["mine"], False)

# -- output projection -----------------------------------------------------
check("a dotted path reads through", pluck({"a": {"b": 2}}, "a.b"), 2)
check("a missing path is None", pluck({"a": {}}, "a.b.c"), None)
check("tabs are projected",
      as_tsv({"data": [{"id": 1, "artist": {"name": "X"}}]},
             ["id", "artist.name"], header=False), "1\tX")

# -- which duplicate survives ---------------------------------------------
sys.argv = ["selftest"]
from dz_playlist import better, key, song_key

lossy = {"id": 1, "readable": True, "lossless": False}
lossless = {"id": 2, "readable": True, "lossless": True}
dead = {"id": 3, "readable": False, "lossless": True}
check("lossless beats lossy", better(lossy, lossless)["id"], 2)
check("the order of the arguments does not matter",
      better(lossless, lossy)["id"], 2)
check("playable beats unplayable", better(dead, lossy)["id"], 1)
check("a tie keeps the first", better(lossless, dict(lossless, id=9))["id"], 2)
check("an ISRC is the identity when present",
      key({"isrc": "AB", "artist": "x", "title": "y"}), ("isrc", "AB"))
check("without an ISRC, artist and title are",
      key({"isrc": None, "artist": "The Beatles", "title": "Help!"}),
      ("song", "the beatles", "help"))
check("the song key ignores the ISRC",
      song_key({"isrc": "AB", "artist": "A", "title": "B"}), ("song", "a", "b"))

# -- the skills mirror -----------------------------------------------------
# Claude Code loads .claude/skills/; anything else reads .agents/skills/. Both
# must exist and must say the same thing, and a mirror kept by good intentions
# stops being a mirror — so it is checked here.
ROOT = Path(__file__).resolve().parent.parent
CLAUDE_SKILLS, AGENT_SKILLS = ROOT / ".claude/skills", ROOT / ".agents/skills"
SYNC = "rsync -a --delete .claude/skills/ .agents/skills/"


def skill_tree(base):
    if not base.is_dir():
        return None
    return {p.relative_to(base).as_posix(): p.read_bytes()
            for p in sorted(base.rglob("*")) if p.is_file()}


claude, agents = skill_tree(CLAUDE_SKILLS), skill_tree(AGENT_SKILLS)
if claude is None or agents is None:
    FAILED.append(f"a skills directory is missing — run: {SYNC}")
else:
    for name in sorted(set(claude) | set(agents)):
        if name not in agents:
            FAILED.append(f"{name} is only in .claude/skills — run: {SYNC}")
        elif name not in claude:
            FAILED.append(f"{name} is only in .agents/skills — run: {SYNC}")
        elif claude[name] != agents[name]:
            FAILED.append(f"{name} differs between the two — run: {SYNC}")
    check_true("there are skills to mirror", claude)

if FAILED:
    print(f"{len(FAILED)} checks failed:")
    for line in FAILED:
        print(f"  {line}")
    sys.exit(1)
print("all checks passed")
