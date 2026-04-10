"""Create required HuggingFace repos for Darwin Image deployment.

Creates:
    1. FINAL-Bench/Darwin-Image-v1 (model, private)
    2. FINAL-Bench/darwin-image-merger (space, private, A100)
    3. FINAL-Bench/darwin-image-gen (space — already exists, skipped)

Usage:
    HF_TOKEN=hf_... python create_repos.py
"""

import argparse
import os
import sys

from huggingface_hub import HfApi


MODEL_REPO = "FINAL-Bench/Darwin-Image-v1"
MERGER_SPACE = "FINAL-Bench/darwin-image-merger"
INFERENCE_SPACE = "FINAL-Bench/darwin-image-gen"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", type=str, default=None)
    parser.add_argument("--public", action="store_true", help="Create repos as public (default: private)")
    args = parser.parse_args()

    token = args.token or os.environ.get("HF_TOKEN")
    if not token:
        print("ERROR: HF_TOKEN not set")
        sys.exit(1)

    api = HfApi(token=token)
    private = not args.public

    print(f"{'='*60}")
    print(f"Darwin Image — HuggingFace Repo Creation")
    print(f"Private: {private}")
    print(f"{'='*60}\n")

    # 1. Model repo
    print(f"[1/3] Creating model repo: {MODEL_REPO}")
    try:
        url = api.create_repo(
            repo_id=MODEL_REPO,
            repo_type="model",
            private=private,
            exist_ok=True,
        )
        print(f"      ✓ {url}")
    except Exception as exc:
        print(f"      ✗ Failed: {exc}")
        sys.exit(1)

    # 2. Merger Space
    print(f"\n[2/3] Creating merger Space: {MERGER_SPACE}")
    try:
        url = api.create_repo(
            repo_id=MERGER_SPACE,
            repo_type="space",
            space_sdk="gradio",
            space_hardware="a100-large",
            private=private,
            exist_ok=True,
        )
        print(f"      ✓ {url}")
    except Exception as exc:
        # Some HF versions don't accept space_hardware in create_repo
        try:
            url = api.create_repo(
                repo_id=MERGER_SPACE,
                repo_type="space",
                space_sdk="gradio",
                private=private,
                exist_ok=True,
            )
            print(f"      ✓ {url} (hardware must be set via UI: a100-large)")
        except Exception as exc2:
            print(f"      ✗ Failed: {exc2}")
            sys.exit(1)

    # 3. Inference Space (already exists per task description)
    print(f"\n[3/3] Checking inference Space: {INFERENCE_SPACE}")
    try:
        info = api.space_info(INFERENCE_SPACE)
        print(f"      ✓ Already exists. Stage: {info.runtime.stage if info.runtime else 'unknown'}")
    except Exception as exc:
        print(f"      ! Not found, creating...")
        try:
            url = api.create_repo(
                repo_id=INFERENCE_SPACE,
                repo_type="space",
                space_sdk="gradio",
                space_hardware="a100-large",
                private=private,
                exist_ok=True,
            )
            print(f"      ✓ {url}")
        except Exception as exc2:
            print(f"      ✗ Failed: {exc2}")
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"✓ Done. Next: python deploy_all.py")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
