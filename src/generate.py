#!/usr/bin/env python3
"""Pain Cave Thumbnail Generator — drives ComfyUI for track artwork."""

import argparse
import os
import sys


COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://localhost:8188")


def generate(track_name: str, genre: str, mood: str, output: str):
    """Generate a thumbnail for a track."""
    # TODO: Load workflow JSON, swap prompt, POST to ComfyUI, download result
    print(f"Would generate thumbnail for '{track_name}' ({genre}, {mood})")
    print(f"ComfyUI: {COMFYUI_URL}")
    print(f"Output: {output}")
    print("Not yet implemented.")


def main():
    parser = argparse.ArgumentParser(
        prog="generate.py",
        description="Pain Cave Thumbnail Generator",
    )
    parser.add_argument("--track-name", required=True, help="Track title")
    parser.add_argument("--genre", default="electronic", help="Music genre")
    parser.add_argument("--mood", default="intense", help="Track mood/energy")
    parser.add_argument("-o", "--output", default="thumbnail.png", help="Output image path")

    args = parser.parse_args()
    generate(args.track_name, args.genre, args.mood, args.output)


if __name__ == "__main__":
    main()
