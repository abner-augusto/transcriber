"""Robust HuggingFace model downloader using snapshot_download."""

import argparse
import sys
import time
from pathlib import Path
from huggingface_hub import snapshot_download


def main():
    parser = argparse.ArgumentParser(description="Download Hugging Face model to local directory")
    parser.add_argument("repo_id", type=str, help="Hugging Face repo ID (e.g. Qwen/Qwen3-ASR-1.7B-hf)")
    parser.add_argument("local_dir", type=Path, help="Local destination directory")
    parser.add_argument("--max-workers", type=int, default=4, help="Max parallel download workers")
    args = parser.parse_args()

    args.local_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {args.repo_id} to {args.local_dir} (workers={args.max_workers})...", flush=True)

    start = time.time()
    path = snapshot_download(
        repo_id=args.repo_id,
        local_dir=str(args.local_dir),
        max_workers=args.max_workers,
    )
    elapsed = time.time() - start
    print(f"\nDownload completed in {elapsed:.1f}s: {path}", flush=True)


if __name__ == "__main__":
    main()
