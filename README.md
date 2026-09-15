# paincave-thumbnail

Generates cover art for a Pain Cave track. Pipeline: SUNO → `paincave-audio` →
`paincave-analysis` (hash, peaks, m4a) → **thumbnail**, then `bun run db:sync-tracks`
in `../paincave` ([content flow](../paincave/docs/architecture.md#content-flow-as-built)).

**Status:** active. Last step of `../paincave/bin/import.sh` (step 3/3); also
run standalone via `../paincave/bin/thumbnail.sh`.

Big picture: [`../paincave/docs/architecture.md`](../paincave/docs/architecture.md),
current work: [`../paincave/docs/plan.md`](../paincave/docs/plan.md).

## Setup

```bash
uv sync   # Python >=3.11
```

Pillow >=11.3 with AVIF support is required. The CLI checks codec support before
paid generation. AVIF is the sole thumbnail format.

## Environment

No local `.env`. Keys live in `../paincave/.env`, loaded by
`../paincave/bin/_common.sh` when you go through the paincave wrappers.
This repo's own `bin/thumbnail.sh` loads nothing — export the vars yourself.
Variables and defaults: [`../paincave/docs/development.md` §4](../paincave/docs/development.md#4-environment-variables).

| Variable | Default / when needed |
|---|---|
| `AI_MODEL` | `anthropic:claude-haiku-4-5`; used only for a fresh prompt |
| `IMAGE_MODEL` | `Rundiffusion/Juggernaut-Lightning-Flux` for a new recipe; overrides a saved model when set |
| `ANTHROPIC_API_KEY` | Needed only when asking Claude for a fresh prompt |
| `TOGETHER_API_KEY` | Needed only when rendering a new image |

Skipping existing artwork, repairing derivatives and printing a cached prompt need
no API keys. Rendering a saved/supplied prompt needs only the Together key.
Remove or update any old `IMAGE_MODEL=black-forest-labs/FLUX.1-schnell` override:
Together now marks that serverless endpoint unavailable, and the CLI rejects it
before spending on a prompt. [Provider status](https://www.together.ai/models/flux-1-schnell-2).

## Usage

The argument is a track hash (looked up in `PAINCAVE_TRACKS_DIR`) or a path to
a track directory. `metadata.json` is required only to ask Claude for a new prompt.

```bash
../paincave/bin/thumbnail.sh 33b46e5c8cdd                       # skip, repair, or generate
../paincave/bin/thumbnail.sh ../paincave-tracks/33b46e5c8cdd/   # by path
../paincave/bin/thumbnail.sh 33b46e5c8cdd --prompt-only         # save/reuse prompt, print it
../paincave/bin/thumbnail.sh 33b46e5c8cdd --prompt-only --new-prompt  # pay for fresh concept
../paincave/bin/thumbnail.sh 33b46e5c8cdd --regenerate --seed 42 # render using saved prompt
../paincave/bin/thumbnail.sh 33b46e5c8cdd --regenerate --prompt-file ./concept.txt
uv run python src/generate.py --help
```

**Default behavior protects existing art.** A complete valid set is skipped, even
if you pass a different seed, prompt or model. Missing/corrupt sizes are rebuilt
from the valid 512px AVIF master locally. If that master is invalid but other
artwork exists, the CLI requires `--regenerate` before a paid replacement.

`--regenerate` makes one image request, reusing the saved prompt and seed unless
overridden. Use `--seed` for a different image variation, `--new-prompt` for a
new Claude concept, or `--prompt-file` for a UTF-8 prompt or saved JSON recipe.
`--new-prompt` and `--prompt-file` are mutually exclusive. Prompt-only operations
can change the saved prompt without changing artwork.

## How it works

1. Reuse `thumbnail-prompt.json` when present. Otherwise Claude (`AI_MODEL`) turns
   `title`, `genres`, `bpm`, `key` from `metadata.json` into one image prompt.
   System prompt (`SYSTEM_PROMPT` in `src/generate.py`):
   surrealist fine art (Magritte, de Chirico, Dalí), night cities, big skies,
   cosmic vistas; title as loose theme only; BPM sets mood; bold compositions
   that read at 128px.
2. Save the prompt and image settings **before** requesting a render. Together
   renders one 512×512 image using `response_format="base64"`; the response field
   is `b64_json`. The response must decode into exactly 512×512.
3. Pillow resizes with LANCZOS and encodes AVIF at quality 60, speed 8. All four
   files are encoded before publication from a recoverable staging directory:

| File | Size |
|------|------|
| `thumb.avif` | 512×512 |
| `thumb_256.avif` | 256×256 |
| `thumb_128.avif` | 128×128 |
| `thumb_64.avif` | 64×64 |

Speed 8 favors quick encoding on Pillow's 0–10 scale.
[Pillow AVIF options](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#avif).

All four sizes cost one image request in total. Fresh renders encode each size
directly from the provider's decoded PNG. Repairing from a lossy master introduces
another compression generation. The app's thumbnail URLs use `.avif` exclusively.

### Saved recipes and recovery

- `thumbnail-prompt.json`: most recently prepared prompt/recipe. Stores version,
  prompt, prompt model, image model, seed, requested steps and dimensions. Both
  `--prompt-only` and generation save it. It can differ from the current artwork.
- `thumbnail.json`: recipe of the last successfully published generated image.
  Use it with `--prompt-file` to return to that artwork's prompt/settings.
- `.thumbnail-stage/`: completed image outputs and checksums awaiting publication.
  If publication is interrupted, the next ordinary invocation finishes it and
  completes any missing sizes locally, then exits without an API call, even
  with `--regenerate`. Keep this directory to recover a paid render.
- `.thumbnail.lock`: persistent lock file; macOS/Linux release the lock when the
  process exits. Do not delete it while a generator is running.

Encoding failures leave existing art unchanged. Each file replacement is atomic;
the four replacements are not one transaction, so a reader can briefly see mixed
versions during publication. Staged output allows the next run to finish the set.
This is process-interruption recovery, not a power-loss durability guarantee.

After an image request fails, retry the ordinary command (add `--regenerate` if
replacing existing art). Omit `--new-prompt` to reuse the saved concept and seed.
Claude has a 30-second request timeout and one automatic retry. Together has a
60-second request timeout and no automatic retries: an ambiguous timeout may have
already generated a billed image, so rerunning explicitly can incur another charge.

Juggernaut Lightning starts at 28 steps, matching Together's published example;
`--steps` overrides this and is saved. Switching to another model drops the old
model's step count and uses provider defaults unless `--steps` is supplied.
Model overrides must support this CLI's square 512px/base64 request contract.
These settings have offline contract coverage; live image quality, cost and
latency have not been benchmarked. [Together model example](https://www.together.ai/models/juggernaut-lightning-flux),
[image API](https://docs.together.ai/reference/post-images-generations).

A saved prompt, seed and settings support repeatable requests; provider model
updates can still change pixels. Preserve the accepted master. Metadata changes
do not invalidate an approved prompt automatically.

Why an LLM instead of templates: rule-based prompts were repetitive and leaked
title words into the prompt, which FLUX renders as visible text. For the same
reason the prompt never mentions text at all — even "no text" produces text.

## Verification

```bash
uv run python -m unittest discover -s tests -v
uv run python src/generate.py --help
bash -n bin/thumbnail.sh
```

The tests use temporary directories and mocked HTTP transports, with socket
connections blocked. They cover provider contracts, real AVIF encoding and
decoding, recipe reuse, skipping and repair from the AVIF master, codec validation,
locking and interrupted publication; no paid API calls.

## Known limitations

- Fresh concepts use initial file metadata, not later admin edits in SQLite.
- Repeating the parent import skips an existing track, even after thumbnail
  failure; retry with the thumbnail wrapper directly.
- A process killed before encoding finishes can leave `.thumbnail-encode-*`
  temporary directories. They are not resumable; completed `.thumbnail-stage`
  batches are. Hidden cleanup directories can also remain after a killed cleanup.

Historical findings and pricing research: [2026-09-15 audit](docs/research/2026-09-15-thumbnail-audit.md).
