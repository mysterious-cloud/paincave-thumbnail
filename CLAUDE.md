# Pain Cave Thumbnail

Local thumbnail generation for Pain Cave tracks using Stable Diffusion via ComfyUI on Apple Silicon.

## Philosophy

- **Ship fast, no slop.** Generated art should match the track's mood and energy.
- **Brief code.** Thin Python wrapper around ComfyUI workflows.
- **Local-first.** Everything runs on MacBook, no cloud dependencies.
- **Zero warnings, zero errors.** Verify before committing.

## Tech Stack

- **Runtime:** Python 3.11+ via uv
- **Image Generation:** Stable Diffusion via ComfyUI
- **Image Processing:** Pillow
- **CLI:** argparse

## Project Structure

```
src/           # Source modules (flat layout)
docs/          # Specs and standards
```

## How It Works

1. Takes track metadata (name, genre, mood, BPM) as input
2. Builds a prompt from metadata
3. Sends workflow JSON to ComfyUI REST API
4. Polls until generation complete
5. Retrieves and post-processes the generated image
6. Outputs sized thumbnails for the app

## Environment Variables

- `COMFYUI_URL` — ComfyUI API endpoint (default `http://localhost:8188`)
- `PAINCAVE_TRACKS_DIR` — Default tracks directory. CLI args override.

## Conventions

- Flat `src/` layout, no packages or `__init__.py`
- ComfyUI workflows exported as JSON and checked into repo
- All CLI commands use argparse
- ComfyUI must be running as a background process

## Standards Documents

- [docs/thumbnail-generation.md](docs/thumbnail-generation.md) — Workflow design, prompt templates, output specs

## Running

```bash
# ComfyUI must be running first
uv run src/generate.py --track-name "Midnight Grind" --genre "dark techno" --mood "aggressive" -o thumbnail.png
```

## AI Assistant Guidelines

### Code Generation Rules
- **No slop.** Every generated line must be intentional.
- **Brief is better.** Fewer lines, same clarity.
- **Verify with `uv run`** before considering anything done.
- **No unnecessary abstractions** — this is a CLI tool.
- Workflow JSON is the source of truth for image generation parameters.

### Before Committing Code
1. Zero errors when running
2. Code is formatted
3. Feature manually tested
4. Standards docs reviewed — add, update, or remove as needed

### Communication Style
- Be direct. Skip preamble.
- Propose solutions, don't ask permission for obvious fixes.
- When uncertain, ask one clear question.
