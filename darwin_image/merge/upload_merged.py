"""Upload the merged Darwin-Image-v1 pipeline to HuggingFace Hub.

Usage:
    python upload_merged.py \
        --folder ./Darwin-Image-v1 \
        --repo FINAL-Bench/Darwin-Image-v1 \
        --private

Requires HF_TOKEN env var with write access to the target org.
"""

import argparse
import os
import sys

from huggingface_hub import HfApi, upload_folder


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=str, required=True, help="Local folder containing merged pipeline")
    parser.add_argument("--repo", type=str, default="FINAL-Bench/Darwin-Image-v1")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--commit-message", type=str, default="Upload Darwin-Image-v1 fused pipeline")
    args = parser.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        print("[upload] ERROR: HF_TOKEN environment variable not set")
        sys.exit(1)

    if not os.path.isdir(args.folder):
        print(f"[upload] ERROR: folder not found: {args.folder}")
        sys.exit(1)

    api = HfApi(token=token)

    print(f"[upload] Ensuring repo {args.repo} exists...")
    api.create_repo(
        repo_id=args.repo,
        repo_type="model",
        private=args.private,
        exist_ok=True,
    )

    print(f"[upload] Uploading {args.folder} → {args.repo}...")
    upload_folder(
        folder_path=args.folder,
        repo_id=args.repo,
        repo_type="model",
        commit_message=args.commit_message,
        token=token,
        ignore_patterns=["*.tmp", "__pycache__", "*.pyc"],
    )

    print(f"[upload] ✓ Upload complete: https://huggingface.co/{args.repo}")


if __name__ == "__main__":
    main()
