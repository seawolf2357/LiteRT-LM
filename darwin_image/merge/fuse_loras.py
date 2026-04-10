"""Fuse 4 LoRAs into Z-Image Turbo AND bundle Darwin-4B-David VLM into a
single unified model repository.

Produces a self-contained diffusers pipeline directory with both:
  - Z-Image Turbo (6B DiT, LoRA-fused) at the repo root
  - Darwin-4B-David VLM (Gemma4, ~16GB) under the `vlm_judge/` subfolder

After upload, consumers load via:
    pipe = DiffusionPipeline.from_pretrained("FINAL-Bench/Darwin-Image-v1")
    judge = AutoModel.from_pretrained("FINAL-Bench/Darwin-Image-v1",
                                      subfolder="vlm_judge")

Usage:
    python fuse_loras.py \
        --manifest lora_manifest.yaml \
        --output ./Darwin-Image-v1 \
        --dtype bfloat16 \
        --vlm-source FINAL-Bench/Darwin-4B-David

Design:
    1. Load base Z-Image Turbo (bf16)
    2. For each LoRA in manifest:
       a. Load weights into pipeline
       b. fuse_lora(lora_scale=X)
       c. unload_lora_weights()
    3. save_pretrained(output_dir)  -> Z-Image components
    4. snapshot_download(Darwin-4B-David) -> copy into output_dir/vlm_judge/
    5. Write fuse_report.json + copy lora_manifest.yaml


All LoRAs share Z-Image's DiT architecture (dim=3840), so direct fusing
works without rank alignment or SVD projection.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import torch
import yaml


def load_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def inspect_lora_targets(pipe, label: str) -> set:
    """Return the set of target modules currently loaded on the transformer."""
    try:
        transformer = pipe.transformer
        targets = set()
        for name, module in transformer.named_modules():
            if hasattr(module, "lora_A") or "lora" in name.lower():
                targets.add(name)
        return targets
    except Exception as exc:
        print(f"[fuse] could not inspect targets ({label}): {exc}")
        return set()


def main():
    parser = argparse.ArgumentParser(description="Fuse LoRAs into Z-Image Turbo + bundle VLM")
    parser.add_argument("--manifest", type=str, default="lora_manifest.yaml")
    parser.add_argument("--output", type=str, default="./Darwin-Image-v1")
    parser.add_argument("--dtype", type=str, default="bfloat16", choices=["bfloat16", "float16", "float32"])
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--test", action="store_true", help="Run validation prompts after fusing")
    parser.add_argument("--strict", action="store_true", help="Abort on any LoRA load failure")
    parser.add_argument("--vlm-source", type=str, default="FINAL-Bench/Darwin-4B-David",
                        help="Source VLM repo to bundle into output/vlm_judge/")
    parser.add_argument("--skip-vlm", action="store_true", help="Skip VLM bundling (Z-Image only)")
    args = parser.parse_args()

    from diffusers import DiffusionPipeline
    from huggingface_hub import hf_hub_download, snapshot_download

    dtype = getattr(torch, args.dtype)
    manifest = load_manifest(args.manifest)

    base_model = manifest["base_model"]
    print(f"\n{'='*60}")
    print(f"[fuse] Darwin Image LoRA Merger")
    print(f"[fuse] Base: {base_model}")
    print(f"[fuse] Output: {args.output}")
    print(f"[fuse] Dtype: {args.dtype}")
    print(f"{'='*60}\n")

    token = os.environ.get("HF_TOKEN")

    print(f"[fuse] Loading {base_model}...")
    pipe = DiffusionPipeline.from_pretrained(
        base_model,
        torch_dtype=dtype,
        token=token,
    )
    pipe = pipe.to(args.device)
    print(f"[fuse] Base model loaded successfully.")

    fuse_report = {
        "base_model": base_model,
        "dtype": args.dtype,
        "loras_applied": [],
        "loras_skipped": [],
    }

    # Sequential fuse — each LoRA's effect accumulates into base weights
    for entry in manifest["loras"]:
        repo_id = entry["repo_id"]
        scale = float(entry["scale"])
        adapter_name = entry.get("adapter_name", repo_id.split("/")[-1])
        purpose = entry.get("purpose", "")

        print(f"\n[fuse] === {adapter_name} ({repo_id}) scale={scale} ===")
        print(f"[fuse] Purpose: {purpose}")

        try:
            pipe.load_lora_weights(repo_id, adapter_name=adapter_name, token=token)
        except TypeError:
            # Older diffusers doesn't accept adapter_name
            try:
                pipe.load_lora_weights(repo_id, token=token)
            except Exception as exc:
                msg = f"[fuse] FAILED to load {repo_id}: {exc}"
                print(msg)
                fuse_report["loras_skipped"].append({"repo_id": repo_id, "reason": str(exc)})
                if args.strict:
                    sys.exit(1)
                continue
        except Exception as exc:
            msg = f"[fuse] FAILED to load {repo_id}: {exc}"
            print(msg)
            fuse_report["loras_skipped"].append({"repo_id": repo_id, "reason": str(exc)})
            if args.strict:
                sys.exit(1)
            continue

        try:
            pipe.fuse_lora(lora_scale=scale)
            pipe.unload_lora_weights()
            fuse_report["loras_applied"].append({
                "repo_id": repo_id,
                "adapter_name": adapter_name,
                "scale": scale,
                "purpose": purpose,
            })
            print(f"[fuse] ✓ {adapter_name} fused at scale {scale}")
        except Exception as exc:
            msg = f"[fuse] FAILED to fuse {repo_id}: {exc}"
            print(msg)
            fuse_report["loras_skipped"].append({"repo_id": repo_id, "reason": str(exc)})
            try:
                pipe.unload_lora_weights()
            except Exception:
                pass
            if args.strict:
                sys.exit(1)

    print(f"\n[fuse] All LoRAs processed. Applied: {len(fuse_report['loras_applied'])}, "
          f"Skipped: {len(fuse_report['loras_skipped'])}")

    # Save merged Z-Image pipeline
    print(f"\n[fuse] Saving merged Z-Image pipeline to {args.output}...")
    os.makedirs(args.output, exist_ok=True)
    pipe.save_pretrained(args.output, safe_serialization=True)

    # Free GPU before VLM download
    del pipe
    torch.cuda.empty_cache()

    # -------- VLM bundling: copy Darwin-4B-David into vlm_judge/ subdir --------
    if not args.skip_vlm:
        vlm_dir = os.path.join(args.output, "vlm_judge")
        print(f"\n[fuse] Bundling VLM {args.vlm_source} into {vlm_dir}/...")
        os.makedirs(vlm_dir, exist_ok=True)
        try:
            snapshot_download(
                repo_id=args.vlm_source,
                repo_type="model",
                local_dir=vlm_dir,
                token=token,
                ignore_patterns=["*.png", "*.jpg", "*.jpeg", "*.md", "*.json.backup"],
            )
            # Count downloaded size
            total_bytes = 0
            for root, _, files in os.walk(vlm_dir):
                for f in files:
                    total_bytes += os.path.getsize(os.path.join(root, f))
            fuse_report["vlm_bundled"] = {
                "source": args.vlm_source,
                "size_gb": round(total_bytes / (1024 ** 3), 2),
            }
            print(f"[fuse] ✓ VLM bundled: {total_bytes / (1024 ** 3):.2f} GB")
        except Exception as exc:
            msg = f"[fuse] VLM bundling FAILED: {exc}"
            print(msg)
            fuse_report["vlm_bundled"] = {"source": args.vlm_source, "error": str(exc)}
            if args.strict:
                sys.exit(1)
    else:
        print(f"[fuse] --skip-vlm set, skipping VLM bundling")
        fuse_report["vlm_bundled"] = {"skipped": True}

    # Save fuse report
    report_path = os.path.join(args.output, "fuse_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(fuse_report, f, indent=2, ensure_ascii=False)
    print(f"[fuse] Report saved to {report_path}")

    # Optional validation (reloads the saved pipeline — pipe was freed)
    if args.test:
        print(f"\n[fuse] Running validation prompts...")
        test_pipe = DiffusionPipeline.from_pretrained(
            args.output, torch_dtype=dtype
        ).to(args.device)
        test_pipe.set_progress_bar_config(disable=True)
        for i, prompt in enumerate(manifest.get("validation", {}).get("test_prompts", [])):
            try:
                img = test_pipe(
                    prompt=prompt,
                    num_inference_steps=8,
                    guidance_scale=3.5,
                    height=512,
                    width=512,
                    generator=torch.Generator(args.device).manual_seed(42 + i),
                ).images[0]
                out_path = os.path.join(args.output, f"validation_{i:02d}.png")
                img.save(out_path)
                print(f"[fuse] ✓ Validation {i}: {prompt[:50]}... → {out_path}")
            except Exception as exc:
                print(f"[fuse] Validation {i} failed: {exc}")
        del test_pipe
        torch.cuda.empty_cache()

    print(f"\n[fuse] ✓ Done. Unified model at: {args.output}")
    print(f"[fuse]   Contains Z-Image Turbo (LoRA fused) + Darwin-4B-David VLM")


if __name__ == "__main__":
    main()
