#!/usr/bin/env python3
"""
mb-wallpaper-sort-ce.py
Multi-format video to AVIF wallpaper extractor with intelligent filtering.

Extracts frames from video, filters out unwanted images (black, white, low-detail),
and converts to AVIF format.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from collections import defaultdict

try:
    from PIL import Image
    import numpy as np
except ImportError:
    print("Error: PIL/Pillow and numpy required. Install with:", file=sys.stderr)
    print("  pip install Pillow numpy", file=sys.stderr)
    sys.exit(1)


class WallpaperSorter:
    def __init__(self, config_path="config.json"):
        """Initialize sorter with config."""
        self.config = self._load_config(config_path)
        self.stats = {
            "extracted": 0,
            "brightness_rejected": 0,
            "variance_rejected": 0,
            "passed": 0,
            "converted": 0,
        }

    def _load_config(self, config_path):
        """Load configuration from JSON file."""
        try:
            with open(config_path) as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Config file {config_path} not found. Using defaults.", file=sys.stderr)
            return {
                "brightness_min": 30,
                "brightness_max": 225,
                "variance_threshold": 50,
                "avif_quality": 95,
                "fps": 2,
            }

    def _run_cmd(self, cmd, description=""):
        """Run a shell command and return success status."""
        try:
            result = subprocess.run(
                cmd,
                shell=isinstance(cmd, str),
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            if description:
                print(f"Error {description}: {e.stderr}", file=sys.stderr)
            else:
                print(f"Command failed: {e.stderr}", file=sys.stderr)
            return False
        except FileNotFoundError as e:
            print(f"Command not found: {e}", file=sys.stderr)
            return False

    def extract_frames(self, video_path, output_dir, fps=None):
        """Extract frames from video using ffmpeg."""
        if fps is None:
            fps = self.config.get("fps", 2)

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"Extracting frames at {fps} fps from {video_path}...")

        # ffmpeg command: extract frames at specified fps
        output_pattern = str(output_dir / "frame_%06d.png")
        cmd = [
            "ffmpeg",
            "-i",
            video_path,
            "-vf",
            f"fps={fps}",
            "-q:v",
            "2",  # high quality
            output_pattern,
        ]

        try:
            result = subprocess.run(
                cmd, check=True, capture_output=True, text=True
            )
            # Count extracted frames
            frames = list(output_dir.glob("frame_*.png"))
            self.stats["extracted"] = len(frames)
            print(f"  ✓ Extracted {self.stats['extracted']} frames")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error extracting frames: {e.stderr}", file=sys.stderr)
            return False
        except FileNotFoundError:
            print("Error: ffmpeg not found. Install with: apt install ffmpeg", file=sys.stderr)
            return False

    def get_brightness(self, image_path):
        """Get average brightness of image (0-255)."""
        try:
            img = Image.open(image_path).convert("L")
            return np.mean(np.array(img))
        except Exception as e:
            print(f"Error reading {image_path}: {e}", file=sys.stderr)
            return None

    def get_variance(self, image_path):
        """Get color variance of image (measure of detail/interest)."""
        try:
            img = Image.open(image_path).convert("RGB")
            pixels = np.array(img).reshape(-1, 3)
            # Calculate variance across all color channels
            variance = np.var(pixels)
            return variance
        except Exception as e:
            print(f"Error analyzing {image_path}: {e}", file=sys.stderr)
            return None

    def filter_brightness(self, image_path, min_brightness=None, max_brightness=None):
        """Filter out almost-black and almost-white images."""
        if min_brightness is None:
            min_brightness = self.config.get("brightness_min", 30)
        if max_brightness is None:
            max_brightness = self.config.get("brightness_max", 225)

        brightness = self.get_brightness(image_path)
        if brightness is None:
            return False

        if brightness < min_brightness:
            return False  # too dark
        if brightness > max_brightness:
            return False  # too bright

        return True

    def filter_variance(self, image_path, min_variance=None):
        """Filter out low-detail images (titles, fades, blanks)."""
        if min_variance is None:
            min_variance = self.config.get("variance_threshold", 50)

        variance = self.get_variance(image_path)
        if variance is None:
            return False

        return variance >= min_variance

    def process_frames(self, extracted_dir, filtered_dir, rejected_dir=None):
        """Filter extracted frames based on brightness and variance."""
        extracted_dir = Path(extracted_dir)
        filtered_dir = Path(filtered_dir)
        filtered_dir.mkdir(parents=True, exist_ok=True)

        if rejected_dir:
            rejected_dir = Path(rejected_dir)
            rejected_dir.mkdir(parents=True, exist_ok=True)

        frames = sorted(extracted_dir.glob("frame_*.png"))
        rejection_reasons = defaultdict(int)

        print(f"\nFiltering {len(frames)} frames...")

        for frame in frames:
            # Brightness check
            if not self.filter_brightness(frame):
                self.stats["brightness_rejected"] += 1
                rejection_reasons["brightness"] += 1
                if rejected_dir:
                    frame.rename(rejected_dir / frame.name)
                continue

            # Variance check
            if not self.filter_variance(frame):
                self.stats["variance_rejected"] += 1
                rejection_reasons["variance"] += 1
                if rejected_dir:
                    frame.rename(rejected_dir / frame.name)
                continue

            # Frame passed all filters
            self.stats["passed"] += 1
            frame.rename(filtered_dir / frame.name)

        print(f"  ✓ Passed: {self.stats['passed']} frames")
        print(f"  ✗ Brightness rejected: {self.stats['brightness_rejected']}")
        print(f"  ✗ Variance rejected: {self.stats['variance_rejected']}")

    def convert_to_avif(self, png_dir, output_dir, quality=None):
        """Convert PNG frames to AVIF using magick."""
        if quality is None:
            quality = self.config.get("avif_quality", 95)

        png_dir = Path(png_dir)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        pngs = sorted(png_dir.glob("frame_*.png"))
        if not pngs:
            print("No PNG frames found to convert.", file=sys.stderr)
            return False

        print(f"\nConverting {len(pngs)} PNG frames to AVIF (quality={quality})...")

        for i, png_path in enumerate(pngs, 1):
            avif_path = output_dir / png_path.stem
            avif_path = avif_path.with_suffix(".avif")

            # Check magick availability
            if i == 1:
                result = subprocess.run(
                    ["magick", "--version"],
                    capture_output=True,
                )
                if result.returncode != 0:
                    print(
                        "Error: magick not found. Install ImageMagick with AVIF support.",
                        file=sys.stderr,
                    )
                    return False

            # Convert using magick
            cmd = [
                "magick",
                str(png_path),
                "-quality",
                str(quality),
                "-define",
                "avif:speed=0",
                str(avif_path),
            ]

            if subprocess.run(cmd, capture_output=True).returncode == 0:
                self.stats["converted"] += 1
                if i % 10 == 0 or i == len(pngs):
                    print(f"  {i}/{len(pngs)} converted...")
            else:
                print(f"  Warning: Failed to convert {png_path.name}", file=sys.stderr)

        print(f"  ✓ Successfully converted {self.stats['converted']} frames")
        return True

    def run(self, video_path, output_dir, keep_pngs=False):
        """Run the complete pipeline."""
        video_path = Path(video_path)
        output_dir = Path(output_dir)

        if not video_path.exists():
            print(f"Error: Video file not found: {video_path}", file=sys.stderr)
            return False

        # Setup work directory
        work_dir = Path("work")
        extracted_dir = work_dir / "extracted"
        filtered_dir = work_dir / "filtered"
        rejected_dir = work_dir / "rejected"

        print(f"Working directory: {work_dir}")
        print(f"Output directory: {output_dir}\n")

        # Step 1: Extract frames
        if not self.extract_frames(str(video_path), extracted_dir):
            return False

        # Step 2: Filter frames
        self.process_frames(extracted_dir, filtered_dir, rejected_dir)

        # Step 3: Convert to AVIF
        if not self.convert_to_avif(filtered_dir, output_dir):
            return False

        # Print summary
        self._print_summary(keep_pngs)
        return True

    def _print_summary(self, keep_pngs=False):
        """Print processing summary."""
        print("\n" + "=" * 60)
        print("PROCESSING SUMMARY")
        print("=" * 60)
        print(f"Frames extracted:      {self.stats['extracted']}")
        print(f"Brightness rejected:   {self.stats['brightness_rejected']}")
        print(f"Variance rejected:     {self.stats['variance_rejected']}")
        print(f"Passed filtering:      {self.stats['passed']}")
        print(f"Converted to AVIF:     {self.stats['converted']}")
        print("=" * 60)

        if not keep_pngs:
            print(
                "\n📝 PNG working directory (./work) will be cleaned up after this session."
            )
        else:
            print("\n📁 PNG working directory kept at ./work for review.")

        print(f"✅ AVIF output in: ./output/avif")


def main():
    parser = argparse.ArgumentParser(
        description="Extract, filter, and convert video frames to AVIF wallpapers"
    )
    parser.add_argument("video", help="Input video file (mp4, mkv, webm)")
    parser.add_argument(
        "-o", "--output",
        default="./output/avif",
        help="Output directory for AVIF files (default: ./output/avif)",
    )
    parser.add_argument(
        "-f", "--fps",
        type=float,
        help="Frames per second to extract (overrides config)",
    )
    parser.add_argument(
        "-c", "--config",
        default="config.json",
        help="Config file path (default: config.json)",
    )
    parser.add_argument(
        "--keep-pngs",
        action="store_true",
        help="Keep PNG working directory after completion",
    )
    parser.add_argument(
        "--quality",
        type=int,
        help="AVIF quality 1-100 (overrides config)",
    )

    args = parser.parse_args()

    sorter = WallpaperSorter(args.config)

    # Override config with CLI args if provided
    if args.fps:
        sorter.config["fps"] = args.fps
    if args.quality:
        sorter.config["avif_quality"] = args.quality

    success = sorter.run(args.video, args.output, args.keep_pngs)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
