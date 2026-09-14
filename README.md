# paincave-thumbnail

Generates cover art for a Pain Cave track. Pipeline: SUNO → `paincave-audio` →
`paincave-analysis` (hash, peaks, m4a) → **thumbnail** → Studio → production.

**Status:** active. Last step of `../paincave/bin/import.sh` (step 3/3); also
run standalone via `../paincave/bin/thumbnail.sh`.

Big picture: [`../paincave/docs/architecture.md`](../paincave/docs/architecture.md),
current work: [`../paincave/docs/plan.md`](../paincave/docs/plan.md).

## Setup

```bash
uv sync   # Python >=3.11
```

## Environment

No local `.env`. Keys live in `../paincave/.env`, loaded by
`../paincave/bin/_common.sh` when you go through the paincave wrappers.
This repo's own `bin/thumbnail.sh` loads nothing — export the vars yourself.

| Var | Required | Default |
|-----|----------|---------|
| `ANTHROPIC_API_KEY` | yes (also for `--prompt-only`) | — |
| `TOGETHER_API_KEY` | yes, for image generation | — |
| `AI_MODEL` | no | `anthropic:claude-haiku-4-5` (prefix before `:` is stripped) |
| `IMAGE_MODEL` | no | `black-forest-labs/FLUX.1-schnell` |
| `PAINCAVE_TRACKS_DIR` | no | `../paincave-tracks` (`import.sh` sets it) |

`.env.example` predates the move to `../paincave/.env`.

## Usage

The argument is a track hash (looked up in `PAINCAVE_TRACKS_DIR`) or a path to
a track directory containing `metadata.json`.

```bash
../paincave/bin/thumbnail.sh 33b46e5c8cdd                       # generate
../paincave/bin/thumbnail.sh ../paincave-tracks/33b46e5c8cdd/   # by path
../paincave/bin/thumbnail.sh 33b46e5c8cdd --seed 42             # reproducible
../paincave/bin/thumbnail.sh 33b46e5c8cdd --prompt-only         # print prompt, no image
uv run python src/generate.py --help
```

## How it works

1. Claude (`AI_MODEL`) turns `title`, `bpm`, `key` from `metadata.json` into one
   image prompt. System prompt (`SYSTEM_PROMPT` in `src/generate.py`):
   surrealist fine art (Magritte, de Chirico, Dalí), night cities, big skies,
   cosmic vistas; title as loose theme only; BPM sets mood; bold compositions
   that read at 128px.
2. FLUX (`IMAGE_MODEL`) via Together renders 512×512 with the given or a random
   seed (printed).
3. Pillow writes WebP (quality 85, LANCZOS) into the track directory,
   overwriting existing files:

| File | Size |
|------|------|
| `thumb.webp` | 512×512 |
| `thumb_256.webp` | 256×256 |
| `thumb_128.webp` | 128×128 |
| `thumb_64.webp` | 64×64 |

Why an LLM instead of templates: rule-based prompts were repetitive and leaked
title words into the prompt, which FLUX renders as visible text. For the same
reason the prompt never mentions text at all — even "no text" produces text.

## Known issues

- **Genres never reach the prompt.** `src/generate.py:47` sends
  `meta.get("styleTags", [])`, but `metadata.json` stores `genres`
  (e.g. `33b46e5c8cdd` has `["tech-house", "house"]`); no track in
  `../paincave-tracks` has `styleTags`, so the model always sees `[]`.
