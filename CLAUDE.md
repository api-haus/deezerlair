@AGENTS.md

Claude-specific notes:

- Skills are loaded from `.claude/skills/`, which mirrors `.agents/skills/`
  byte for byte. Edit either, then `rsync -a --delete .claude/skills/
  .agents/skills/` and run `python3 scripts/selftest.py` — it fails when the
  two drift apart.
- Ask the `/hello-deezer` questions with `AskUserQuestion`, in one call.
- `.claude/settings.json` pins the model to Sonnet, so a session started in
  this directory opens on it. That one is tracked, because it is a property of
  the project rather than of a person.
- Keep personal settings in `.claude/settings.local.json`, never in a
  committed file.
