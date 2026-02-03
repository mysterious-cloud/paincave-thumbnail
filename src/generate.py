#!/usr/bin/env python3
"""Pain Cave Thumbnail Generator — FLUX.1-schnell via Together AI."""

import argparse
import base64
import json
import os
import random
import sys
from io import BytesIO
from pathlib import Path

import anthropic
from PIL import Image
from together import Together

TRACKS_DIR = Path(os.environ.get("PAINCAVE_TRACKS_DIR", Path(__file__).parent.parent / ".." / "paincave-tracks"))
SIZES = [256, 128, 64]

SYSTEM_PROMPT = """\
You are a visual concept designer for album artwork. Given track metadata, \
you produce a single image generation prompt for FLUX.1 (a text-to-image AI model).

Rules:
- Describe a vivid surreal scene, abstract 3D object, macro texture, or dreamlike landscape.
- Use the track title as inspiration for the CONCEPT, but never include the title's actual words.
- Each track variant (edits, remixes) should get a distinctly different visual concept.
- Use the genre, BPM, and musical key to inform texture, energy, and color palette.
- Bold simple compositions with large shapes — must look good at 128x128 pixels.
- CRITICAL: Never mention text, typography, letters, words, or writing in ANY way. \
  Simply describe the visual scene without referencing text at all.
- Clean unmarked surfaces only. No signage, labels, logos, or UI elements.
- No people, faces, or human figures.
- Output ONLY the prompt, nothing else. No preamble, no explanation.\
"""


def build_prompt(meta: dict) -> str:
    """Use Claude to generate an image prompt from track metadata."""
    user_msg = json.dumps({
        "title": meta.get("title"),
        "styleTags": meta.get("styleTags", []),
        "bpm": meta.get("bpm"),
        "key": meta.get("key"),
    }, indent=2)

    model = os.environ.get("AI_MODEL", "anthropic:claude-haiku-4-5")
    model_id = model.split(":")[-1]

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model_id,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text.strip()


def generate_image(prompt: str, seed: int) -> Image.Image:
    """Generate a 512x512 image via Together AI."""
    client = Together()
    model = os.environ.get("IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
    response = client.images.generate(
        prompt=prompt,
        model=model,
        width=512,
        height=512,
        seed=seed,
        n=1,
        response_format="b64_json",
    )
    b64 = response.data[0].b64_json
    return Image.open(BytesIO(base64.b64decode(b64)))


# --- Generation ---

def generate(track_hash: str, seed: int | None = None):
    track_dir = TRACKS_DIR / track_hash
    meta_path = track_dir / "metadata.json"

    if not track_dir.is_dir():
        print(f"Track directory not found: {track_dir}", file=sys.stderr)
        sys.exit(1)
    if not meta_path.exists():
        print(f"metadata.json not found: {meta_path}", file=sys.stderr)
        sys.exit(1)

    meta = json.loads(meta_path.read_text())
    title = meta.get("title", track_hash)
    prompt = build_prompt(meta)
    actual_seed = seed if seed is not None else random.randint(0, 2**32 - 1)

    print(f"Track:  {title}")
    print(f"Prompt: {prompt}")
    print(f"Seed:   {actual_seed}")
    model = os.environ.get("IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
    print(f"Generating 512x512 with {model.split('/')[-1]} via Together AI...")

    pil_img = generate_image(prompt, actual_seed)
    pil_img.save(track_dir / "thumbnail.png")
    print(f"Saved:  {track_dir / 'thumbnail.png'}")

    for size in SIZES:
        resized = pil_img.resize((size, size), Image.LANCZOS)
        sized_path = track_dir / f"thumbnail-{size}.png"
        resized.save(sized_path)
        print(f"Saved:  {sized_path}")

    print("Done.")


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(
        prog="generate.py",
        description="Generate thumbnail for a Pain Cave track",
    )
    parser.add_argument("hash", help="Track content hash")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    parser.add_argument("--prompt-only", action="store_true", help="Print prompt and exit")

    args = parser.parse_args()

    if args.prompt_only:
        track_dir = TRACKS_DIR / args.hash
        meta = json.loads((track_dir / "metadata.json").read_text())
        print(build_prompt(meta))
        return

    generate(args.hash, seed=args.seed)


if __name__ == "__main__":
    main()
