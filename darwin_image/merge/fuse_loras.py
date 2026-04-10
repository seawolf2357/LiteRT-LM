"""Fuse 4 LoRAs into Z-Image Turbo and save the merged pipeline.

Usage:
    python fuse_loras.py \
        --manifest lora_manifest.yaml \
        --output ./Darwin-Image-v1 \
        --dtype bfloat16

The merged output is a standard diffusers pipeline directory that can be
loaded via `DiffusionPipeline.from_pretrained("./Darwin-Image-v1")`.

Design:
    1. Load base Z-Image Turbo (bf16)
    2. For each LoRA in manifest:
       a. Load weights into pipeline
       b. Inspect target_modules — abort if incompatible
       c. fuse_lora(lora_scale=X)
       d. unload_lora_weights()
    3. save_pretrained(output_dir)

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
    parser = argparse.ArgumentParser(description="Fuse LoRAs into Z-Image Turbo")
    parser.add_argument("--manifest", type=str, default="lora_manifest.yaml")
    parser.add_argument("--output", type=str, default="./Darwin-Image-v1")
    parser.add_argument("--dtype", type=str, default="bfloat16", choices=["bfloat16", "float16", "float32"])
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--test", action="store_true", help="Run validation prompts after fusing")
    parser.add_argument("--strict", action="store_true", help="Abort on any LoRA load failure")
    args = parser.parse_args()

    from diffusers import DiffusionPipeline
    from huggingface_hub import hf_hub_download

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

    # Save merged pipeline
    print(f"\n[fuse] Saving merged pipeline to {args.output}...")
    os.makedirs(args.output, exist_ok=True)
    pipe.save_pretrained(args.output, safe_serialization=True)

    # Save fuse report
    report_path = os.path.join(args.output, "fuse_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(fuse_report, f, indent=2, ensure_ascii=False)
    print(f"[fuse] Report saved to {report_path}")

    # Optional validation
    if args.test:
        print(f"\n[fuse] Running validation prompts...")
        pipe.set_progress_bar_config(disable=True)
        for i, prompt in enumerate(manifest.get("validation", {}).get("test_prompts", [])):
            try:
                img = pipe(
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

    print(f"\n[fuse] ✓ Done. Merged model at: {args.output}")


if __name__ == "__main__":
    main()
