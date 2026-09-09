# Pain Cave Thumbnail

Thumbnail generation for Pain Cave tracks using FLUX.1-schnell via Together AI.

## Philosophy

- **Ship fast, no slop.** Generated art should match the track's mood and energy.
- **Brief code.** Single-file CLI, no unnecessary abstractions.
- **Zero warnings, zero errors.** Verify before committing.

## Tech Stack

- **Runtime:** Python 3.11+ via uv
- **Image Generation:** FLUX.1-schnell via Together AI API
- **Prompt Generation:** Claude Haiku via Anthropic API
- **Image Processing:** Pillow
- **CLI:** argparse

## Project Structure

```
bin/thumbnail.sh   # Pipeline entry point — sources .env, delegates to generate.py
src/generate.py    # Single-file CLI — prompt generation + image generation + resizing
docs/              # Specs and standards
```

## How It Works

1. Takes a track hash or path as input
2. Reads `metadata.json` from the track directory
3. Sends metadata (title, genres, BPM, key) to Claude to generate an image prompt
4. Generates a 512x512 image with FLUX.1-schnell via Together AI
5. Saves `thumb.webp` (512) and resized versions (256, 128, 64) as WebP

## Environment Variables

- `TOGETHER_API_KEY` — Together AI key (required, used for image generation)
- `ANTHROPIC_API_KEY` — Anthropic API key (required, used for prompt generation)
- `IMAGE_MODEL` — Image model (optional, default `black-forest-labs/FLUX.1-schnell`)
- `AI_MODEL` — LLM model for prompts (optional, default `anthropic:claude-haiku-4-5`)
- `PAINCAVE_TRACKS_DIR` — Default tracks directory. CLI args override.

## Conventions

- Single-file `src/generate.py`, no packages or `__init__.py`
- All CLI commands use argparse
- Accepts track hash or path to track directory

## Standards Documents

- [docs/thumbnail-generation.md](docs/thumbnail-generation.md) — Prompt strategy, model config, output specs
- [Track Pipeline](../paincave/docs/track-pipeline.md) — End-to-end flow from raw audio to production. Where this project fits in the pipeline, track directory structure, shared contracts.

## Running

```bash
# By hash (looks up in PAINCAVE_TRACKS_DIR)
bin/thumbnail.sh 98f755fef882

# By path (direct)
bin/thumbnail.sh ../paincave-tracks/98f755fef882/

# With a fixed seed for reproducibility
bin/thumbnail.sh 98f755fef882 --seed 42

# Print the generated prompt without creating an image
bin/thumbnail.sh 98f755fef882 --prompt-only
```

## AI Assistant Guidelines

### Code Generation Rules
- **No slop.** Every generated line must be intentional.
- **Brief is better.** Fewer lines, same clarity.
- **Verify with `uv run`** before considering anything done.
- **No unnecessary abstractions** — this is a single-file CLI tool.

### Before Committing Code
1. Zero errors when running
2. Code is formatted
3. Feature manually tested
4. Standards docs reviewed — add, update, or remove as needed

### Communication Style
- Be direct. Skip preamble.
- Propose solutions, don't ask permission for obvious fixes.
- When uncertain, ask one clear question.
