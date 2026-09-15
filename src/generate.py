#!/usr/bin/env python3
"""Pain Cave Thumbnail Generator — cached prompts and artwork via Together AI."""

import argparse
import base64
import binascii
import fcntl
import hashlib
import json
import os
import random
import sys
import tempfile
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import anthropic
from PIL import Image, features
from together import Together, TogetherError

TRACKS_DIR = Path(
    os.environ.get(
        "PAINCAVE_TRACKS_DIR", Path(__file__).parent.parent / ".." / "paincave-tracks"
    )
)
OUTPUTS = {
    "thumb.avif": 512,
    "thumb_256.avif": 256,
    "thumb_128.avif": 128,
    "thumb_64.avif": 64,
}
DEFAULT_IMAGE_MODEL = "Rundiffusion/Juggernaut-Lightning-Flux"
DEFAULT_STEPS = {DEFAULT_IMAGE_MODEL: 28}
RETIRED_MODELS = {
    "black-forest-labs/FLUX.1-schnell",
    "black-forest-labs/FLUX.1-schnell-Free",
}
AVIF_QUALITY = 60
AVIF_SPEED = 8

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


def prompt_model() -> str:
    model = os.environ.get("AI_MODEL", "anthropic:claude-haiku-4-5")
    if ":" in model and not model.startswith("anthropic:"):
        raise ValueError("AI_MODEL must name an Anthropic model")
    model = model.removeprefix("anthropic:").strip()
    if not model:
        raise ValueError("AI_MODEL must be nonempty")
    return model


def require_key(name: str):
    if not os.environ.get(name, "").strip():
        raise ValueError(f"{name} is required for this operation")


def build_prompt(meta: dict) -> str:
    require_key("ANTHROPIC_API_KEY")
    message = {key: meta.get(key) for key in ("title", "genres", "bpm", "key")}
    with anthropic.Anthropic(timeout=30, max_retries=1) as client:
        response = client.messages.create(
            model=prompt_model(),
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(message)}],
        )
    if response.stop_reason != "end_turn":
        raise ValueError(f"Prompt generation did not finish: {response.stop_reason}")
    return validate_prompt(
        "\n".join(block.text for block in response.content if block.type == "text")
    )


def validate_prompt(prompt) -> str:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Image prompt must be nonempty text")
    return prompt.strip()


def generate_image(recipe: dict) -> Image.Image:
    # Do not automatically resubmit an image request after an ambiguous timeout.
    with Together(timeout=60, max_retries=0) as client:
        response = client.images.generate(
            prompt=recipe["prompt"],
            model=recipe["image_model"],
            width=512,
            height=512,
            seed=recipe["seed"],
            n=1,
            response_format="base64",
            output_format="png",
            **({"steps": recipe["steps"]} if recipe["steps"] is not None else {}),
        )
    data = getattr(response, "data", None)
    encoded = (
        getattr(data[0], "b64_json", None) if isinstance(data, list) and data else None
    )
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("Together returned no base64 image")
    try:
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(raw)) as img:
            img.load()
            if img.size != (512, 512):
                raise ValueError(f"Expected a 512x512 image, received {img.size}")
            return img.convert("RGB")
    except (OSError, binascii.Error) as exc:
        raise ValueError("Together returned an invalid image") from exc


def resolve_track_dir(track_ref: str) -> Path:
    path = Path(track_ref)
    if not path.is_dir() and "/" not in track_ref and not track_ref.startswith("."):
        path = TRACKS_DIR / track_ref
    if not path.is_dir():
        raise ValueError(f"Track directory not found: {track_ref}")
    return path.resolve()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def atomic_write(path: Path, data: bytes):
    # Same-directory rename keeps each destination complete even on interruption.
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


@contextmanager
def track_lock(track_dir: Path):
    # Keep the inode: unlinking a flock file would let two processes hold locks.
    with (track_dir / ".thumbnail.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(
                "Thumbnail generation is already running for this track"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def valid_image(path: Path, size: int) -> bool:
    try:
        with Image.open(path) as img:
            img.load()
            return img.format == path.suffix[1:].upper() and img.size == (size, size)
    except (OSError, ValueError):
        return False


def require_image_codecs():
    if not features.check("avif"):
        raise ValueError(
            "Pillow lacks AVIF support; install Pillow >=11.3 with AVIF support"
        )


def stage_outputs(
    track_dir: Path, img: Image.Image, names: list[str], recipe: dict | None
):
    """Finish encoding before any active file changes; retain a recoverable batch."""
    with tempfile.TemporaryDirectory(prefix=".thumbnail-encode-", dir=track_dir) as tmp:
        stage = Path(tmp)
        hashes = {}
        resized_images = {img.width: img} if img.width == img.height else {}
        for name in names:
            size = OUTPUTS[name]
            if size not in resized_images:
                resized_images[size] = img.resize(
                    (size, size), Image.Resampling.LANCZOS
                )
            resized = resized_images[size]
            path = stage / name
            resized.save(path, "AVIF", quality=AVIF_QUALITY, speed=AVIF_SPEED)
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (stage / "batch.json").write_bytes(
            json_bytes({"outputs": hashes, "recipe": recipe})
        )
        stage.rename(track_dir / ".thumbnail-stage")
    publish_staged(track_dir)


def publish_staged(track_dir: Path) -> bool:
    stage = track_dir / ".thumbnail-stage"
    if not stage.exists():
        return False
    batch = read_json(stage / "batch.json")
    outputs = batch.get("outputs")
    if (
        not isinstance(outputs, dict)
        or not outputs
        or not outputs.keys() <= OUTPUTS.keys()
        or "recipe" not in batch
        or (batch["recipe"] is not None and not isinstance(batch["recipe"], dict))
    ):
        raise ValueError(
            "Invalid staged thumbnail batch; active artwork was not changed"
        )
    for name, digest in outputs.items():
        data = (stage / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest or not valid_image(
            stage / name, OUTPUTS[name]
        ):
            raise ValueError(
                f"Invalid staged thumbnail: {name}; active artwork was not changed"
            )
    for name in outputs:
        atomic_write(track_dir / name, (stage / name).read_bytes())
    if batch["recipe"] is not None:
        atomic_write(track_dir / "thumbnail.json", json_bytes(batch["recipe"]))
    # Retire the recovery batch before cleanup, so interrupted cleanup is harmless.
    with tempfile.TemporaryDirectory(
        prefix=".thumbnail-cleanup-", dir=track_dir
    ) as tmp:
        stage.rename(Path(tmp) / "published")
    print("Saved thumbnails.", file=sys.stderr)
    return True


def prepare_recipe(
    track_dir: Path,
    *,
    seed=None,
    steps=None,
    prompt_file=None,
    new_prompt=False,
    render=False,
) -> dict:
    cached_path = track_dir / "thumbnail-prompt.json"
    source_path = Path(prompt_file) if prompt_file else cached_path
    cached = None
    if prompt_file or (source_path.exists() and not new_prompt):
        cached = (
            read_json(source_path)
            if source_path.suffix.lower() == ".json"
            else {"prompt": source_path.read_text()}
        )
        validate_prompt(cached.get("prompt"))
        if cached.get("version", 1) != 1:
            raise ValueError("Unsupported saved prompt version")
    settings = cached or {}
    model = os.environ.get(
        "IMAGE_MODEL", settings.get("image_model", DEFAULT_IMAGE_MODEL)
    )
    if not isinstance(model, str) or not model.strip():
        raise ValueError("IMAGE_MODEL must be nonempty")
    effective_steps = (
        steps
        if steps is not None
        else (
            settings.get("steps", DEFAULT_STEPS.get(model))
            if settings.get("image_model", model) == model
            else DEFAULT_STEPS.get(model)
        )
    )
    actual_seed = (
        seed if seed is not None else settings.get("seed", random.randint(0, 2**32 - 1))
    )
    if type(actual_seed) is not int or not 0 <= actual_seed < 2**32:
        raise ValueError("Seed must be an integer between 0 and 4294967295")
    if effective_steps is not None and (
        type(effective_steps) is not int or effective_steps < 1
    ):
        raise ValueError("Steps must be a positive integer")
    if render:
        require_key("TOGETHER_API_KEY")
        if model in RETIRED_MODELS:
            raise ValueError(
                "Together FLUX Schnell is unavailable on serverless; set IMAGE_MODEL to a supported model"
            )
    if cached is not None:
        prompt = validate_prompt(cached["prompt"])
        source = cached.get("prompt_model", "supplied")
    else:
        meta = read_json(track_dir / "metadata.json")
        if not isinstance(meta.get("genres", []), list) or any(
            not isinstance(g, str) for g in meta.get("genres", [])
        ):
            raise ValueError("metadata.json genres must be a list of strings")
        prompt = build_prompt(meta)
        source = prompt_model()
    recipe = {
        "version": 1,
        "prompt": prompt,
        "prompt_model": source,
        "image_model": model,
        "seed": actual_seed,
        "steps": effective_steps,
        "width": 512,
        "height": 512,
    }
    atomic_write(cached_path, json_bytes(recipe))
    return recipe


def generate(
    track_ref: str,
    seed: int | None = None,
    *,
    regenerate=False,
    prompt_only=False,
    prompt_file=None,
    new_prompt=False,
    steps=None,
):
    track_dir = resolve_track_dir(track_ref)
    with track_lock(track_dir):
        if not prompt_only:
            require_image_codecs()
            # A prior completed render can be published without paying again.
            if publish_staged(track_dir):
                print(
                    "Recovered staged artwork; completing any missing sizes locally.",
                    file=sys.stderr,
                )
                regenerate = False
            if not regenerate:
                invalid = [
                    name
                    for name, size in OUTPUTS.items()
                    if not valid_image(track_dir / name, size)
                ]
                if not invalid:
                    print(
                        "Thumbnails already exist; use --regenerate to replace artwork.",
                        file=sys.stderr,
                    )
                    return
                if "thumb.avif" not in invalid:
                    with Image.open(track_dir / "thumb.avif") as master:
                        stage_outputs(track_dir, master, invalid, None)
                    print("Repaired sizes locally; no API calls.", file=sys.stderr)
                    return
                if any((track_dir / name).exists() for name in OUTPUTS):
                    raise ValueError(
                        "Missing or invalid 512px master; use --regenerate to replace existing artwork"
                    )
        recipe = prepare_recipe(
            track_dir,
            seed=seed,
            steps=steps,
            prompt_file=prompt_file,
            new_prompt=new_prompt,
            render=not prompt_only,
        )
        if prompt_only:
            print(recipe["prompt"])
            return
        print(
            f"Generating with {recipe['image_model']}, seed {recipe['seed']}...",
            file=sys.stderr,
        )
        img = generate_image(recipe)
        stage_outputs(track_dir, img, list(OUTPUTS), recipe)


def main():
    parser = argparse.ArgumentParser(
        description="Generate or repair Pain Cave thumbnails"
    )
    parser.add_argument("track", help="Track hash or path to track directory")
    parser.add_argument(
        "--seed", type=int, help="Image seed (default: saved seed, otherwise random)"
    )
    parser.add_argument(
        "--steps", type=int, help="Inference steps (default: saved/model settings)"
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Pay for a render and replace existing artwork",
    )
    parser.add_argument(
        "--prompt-only",
        action="store_true",
        help="Save/reuse the prompt and print it without rendering",
    )
    prompts = parser.add_mutually_exclusive_group()
    prompts.add_argument(
        "--prompt-file",
        type=Path,
        help="Use a UTF-8 prompt or saved JSON recipe without Claude",
    )
    prompts.add_argument(
        "--new-prompt",
        action="store_true",
        help="Ask Claude for a fresh prompt instead of reusing the saved one",
    )
    args = parser.parse_args()
    if args.seed is not None and not 0 <= args.seed < 2**32:
        parser.error("--seed must be between 0 and 4294967295")
    if args.steps is not None and args.steps < 1:
        parser.error("--steps must be positive")
    try:
        generate(
            str(args.track),
            args.seed,
            regenerate=args.regenerate,
            prompt_only=args.prompt_only,
            prompt_file=args.prompt_file,
            new_prompt=args.new_prompt,
            steps=args.steps,
        )
    except (OSError, ValueError, anthropic.APIError, TogetherError) as exc:
        print(f"Thumbnail error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
