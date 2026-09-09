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
WEBP_QUALITY = 85

SYSTEM_PROMPT = """\
You are a visual concept designer for album artwork. Given track metadata, \
you produce a single image generation prompt for FLUX.1 (a text-to-image AI model).

Style — surrealist fine art like Magritte, de Chirico, or Dalí:
- Night cities with glowing windows, neon reflections, rain-slicked streets
- Dramatic cloud formations, skies that dominate the frame
- Surreal cityscapes, impossible architecture, liminal spaces
- Cosmic vistas, nebulae, planets, vast empty space
- Silhouetted figures, distant people, mysterious observers
- Dreamlike atmosphere, mysterious and contemplative
- Rich color palettes, dramatic lighting, deep shadows

Rules:
- Use the track title as loose thematic inspiration, never the literal words.
- Match mood to BPM: slow = mysterious/meditative, fast = intense/dynamic.
- Bold simple compositions — must read well at 128x128 pixels.
- CRITICAL: Never mention text, typography, letters, or writing. Just describe the visual.
- Output ONLY the prompt, nothing else.\
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

def resolve_track_dir(track_ref: str) -> Path:
    """Resolve a track reference to a directory. Accepts hash or path."""
    ref_path = Path(track_ref)
    if ref_path.is_dir():
        return ref_path.resolve()
    if "/" in track_ref or track_ref.startswith("."):
        # Looks like a path but doesn't exist
        print(f"Track directory not found: {track_ref}", file=sys.stderr)
        sys.exit(1)
    # Treat as hash
    return TRACKS_DIR / track_ref


def generate(track_ref: str, seed: int | None = None):
    track_dir = resolve_track_dir(track_ref)
    meta_path = track_dir / "metadata.json"

    if not track_dir.is_dir():
        print(f"Track directory not found: {track_dir}", file=sys.stderr)
        sys.exit(1)
    if not meta_path.exists():
        print(f"metadata.json not found: {meta_path}", file=sys.stderr)
        sys.exit(1)

    meta = json.loads(meta_path.read_text())
    title = meta.get("title", track_dir.name)
    prompt = build_prompt(meta)
    actual_seed = seed if seed is not None else random.randint(0, 2**32 - 1)

    print(f"Track:  {title}")
    print(f"Prompt: {prompt}")
    print(f"Seed:   {actual_seed}")
    model = os.environ.get("IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
    print(f"Generating 512x512 with {model.split('/')[-1]} via Together AI...")

    pil_img = generate_image(prompt, actual_seed)

    # Save full resolution
    full_path = track_dir / "thumb.webp"
    pil_img.save(full_path, "WEBP", quality=WEBP_QUALITY)
    print(f"Saved:  {full_path}")

    # Save resized versions
    for size in SIZES:
        resized = pil_img.resize((size, size), Image.LANCZOS)
        out_path = track_dir / f"thumb_{size}.webp"
        resized.save(out_path, "WEBP", quality=WEBP_QUALITY)
        print(f"Saved:  {out_path}")

    print("Done.")


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(
        prog="generate.py",
        description="Generate thumbnail for a Pain Cave track",
    )
    parser.add_argument("track", help="Track hash or path to track directory")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    parser.add_argument("--prompt-only", action="store_true", help="Print prompt and exit")

    args = parser.parse_args()

    if args.prompt_only:
        track_dir = resolve_track_dir(args.track)
        meta = json.loads((track_dir / "metadata.json").read_text())
        print(build_prompt(meta))
        return

    generate(args.track, seed=args.seed)


if __name__ == "__main__":
    main()
