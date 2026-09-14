# paincave-thumbnail

@README.md

Shared conventions, pipeline and workflow: `../paincave/CLAUDE.md` and
`../paincave/docs/`. Only repo-specific rules below.

## Rules

- Single-file CLI: everything stays in `src/generate.py` (argparse, no package/`__init__.py` structure).
- Keys come from `../paincave/.env`. Never add a local `.env`; never print key values.
- Run through `../paincave/bin/thumbnail.sh` so env is loaded.
- Real runs cost API calls and overwrite `thumb*.webp` in the track directory.
  Iterate on prompts with `--prompt-only`; generate only when asked.
- The image prompt must never mention text, letters or typography — FLUX renders it.
- Output names and sizes are a contract with `getThumbnailUrl` in
  `../paincave/ui/src/lib/track-utils.ts` (documented in
  `../paincave/docs/ui.md`, Thumbnails). Change them together or not at all.
- Verify before done: `uv run python src/generate.py --help`.
