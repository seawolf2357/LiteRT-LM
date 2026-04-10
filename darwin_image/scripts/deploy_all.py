"""Deploy Darwin Image files to HuggingFace.

Uploads:
  1. model_card/ + merge/lora_manifest.yaml → FINAL-Bench/Darwin-Image-v1
  2. space_merger/ + merge/fuse_loras.py + lora_manifest.yaml → FINAL-Bench/darwin-image-merger
  3. space_inference/ + pipeline/ → FINAL-Bench/darwin-image-gen

Usage:
    HF_TOKEN=hf_... python deploy_all.py
    HF_TOKEN=hf_... python deploy_all.py --only merger
    HF_TOKEN=hf_... python deploy_all.py --only inference
"""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi, upload_folder


HERE = Path(__file__).parent.resolve()
ROOT = HERE.parent  # darwin_image/

MODEL_REPO = "FINAL-Bench/Darwin-Image-v1"
MERGER_SPACE = "FINAL-Bench/darwin-image-merger"
INFERENCE_SPACE = "FINAL-Bench/darwin-image-gen"


def copy_tree(src: Path, dst: Path, ignore_patterns=None):
    """Copy src directory contents into dst (dst must exist)."""
    for item in src.iterdir():
        if item.name.startswith(".") and item.name != ".gitkeep":
            continue
        if ignore_patterns and any(p in item.name for p in ignore_patterns):
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def deploy_model_card(api: HfApi, token: str):
    """Upload model card + aether_config.json + lora_manifest.yaml to model repo."""
    print(f"\n[model] Deploying model card to {MODEL_REPO}...")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # README.md (model card)
        shutil.copy(ROOT / "model_card" / "README.md", tmp / "README.md")
        shutil.copy(ROOT / "model_card" / "aether_config.json", tmp / "aether_config.json")
        shutil.copy(ROOT / "merge" / "lora_manifest.yaml", tmp / "lora_manifest.yaml")

        upload_folder(
            folder_path=str(tmp),
            repo_id=MODEL_REPO,
            repo_type="model",
            commit_message="Upload Darwin-Image-v1 model card and AETHER config",
            token=token,
            ignore_patterns=["__pycache__", "*.pyc", ".DS_Store"],
        )
    print(f"[model] ✓ https://huggingface.co/{MODEL_REPO}")


def deploy_merger(api: HfApi, token: str):
    """Upload merger Space files + fuse_loras.py + lora_manifest.yaml + manual_fuse.py."""
    print(f"\n[merger] Deploying merger Space to {MERGER_SPACE}...")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Copy space_merger/* (app.py, requirements.txt, README.md)
        copy_tree(ROOT / "space_merger", tmp)
        # Include the manifest and helper scripts
        shutil.copy(ROOT / "merge" / "lora_manifest.yaml", tmp / "lora_manifest.yaml")
        shutil.copy(ROOT / "merge" / "fuse_loras.py", tmp / "fuse_loras.py")
        shutil.copy(ROOT / "merge" / "upload_merged.py", tmp / "upload_merged.py")
        # Ship the manual_fuse module flat so `from manual_fuse import ...` works
        shutil.copy(ROOT / "pipeline" / "manual_fuse.py", tmp / "manual_fuse.py")

        upload_folder(
            folder_path=str(tmp),
            repo_id=MERGER_SPACE,
            repo_type="space",
            commit_message="Deploy Darwin Image Merger Space with manual LoRA fuse",
            token=token,
            ignore_patterns=["__pycache__", "*.pyc", ".DS_Store"],
        )
    print(f"[merger] ✓ https://huggingface.co/spaces/{MERGER_SPACE}")


def deploy_inference(api: HfApi, token: str):
    """Upload inference Space files + pipeline/ package."""
    print(f"\n[inference] Deploying inference Space to {INFERENCE_SPACE}...")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Copy space_inference/* (app.py, README.md, requirements.txt, packages.txt, assets/)
        copy_tree(ROOT / "space_inference", tmp)
        # Copy pipeline/ as a subdirectory so `from pipeline import ...` works
        pipeline_dst = tmp / "pipeline"
        pipeline_dst.mkdir(exist_ok=True)
        copy_tree(ROOT / "pipeline", pipeline_dst)

        upload_folder(
            folder_path=str(tmp),
            repo_id=INFERENCE_SPACE,
            repo_type="space",
            commit_message="Deploy Darwin Image Gen — AETHER pipeline with VLM judge",
            token=token,
            ignore_patterns=["__pycache__", "*.pyc", ".DS_Store"],
        )
    print(f"[inference] ✓ https://huggingface.co/spaces/{INFERENCE_SPACE}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["model", "merger", "inference", "all"], default="all")
    parser.add_argument("--token", type=str, default=None)
    args = parser.parse_args()

    token = args.token or os.environ.get("HF_TOKEN")
    if not token:
        print("ERROR: HF_TOKEN not set")
        sys.exit(1)

    api = HfApi(token=token)

    print(f"{'='*60}")
    print(f"Darwin Image — HuggingFace Deployment")
    print(f"Target: {args.only}")
    print(f"{'='*60}")

    if args.only in ("model", "all"):
        deploy_model_card(api, token)
    if args.only in ("merger", "all"):
        deploy_merger(api, token)
    if args.only in ("inference", "all"):
        deploy_inference(api, token)

    print(f"\n{'='*60}")
    print(f"✓ Deployment complete!")
    print(f"{'='*60}")
    print(f"\nNext steps:")
    print(f"  1. Set HF_TOKEN secret on both Spaces (via HF UI)")
    print(f"  2. Open {MERGER_SPACE} and click 'Run LoRA Merge' (~10 min)")
    print(f"  3. Once merged model is uploaded, {INFERENCE_SPACE} will auto-load it")
    print(f"  4. Test {INFERENCE_SPACE} with example prompts")


if __name__ == "__main__":
    main()
