"""Manual LoRA fusing for Z-Image Turbo.

Diffusers' automatic `load_lora_weights()` + `fuse_lora()` fails on the
Z-Image LoRAs from the community because:

1. Non-standard filenames — repos use `AWPortrait-Z.safetensors`,
   `lora-women.safetensors`, etc. instead of `pytorch_lora_weights.safetensors`.
2. Key prefix mismatch — community LoRAs use `diffusion_model.layers.N.X.lora_A.weight`
   (the original Z-Image checkpoint naming) while diffusers' ZImageTransformer2DModel
   expects its own internal mapping that the auto-loader cannot always resolve.

This module performs a direct matrix fusing instead:

    W_new = W_base + (B @ A) * (alpha / rank) * scale

where:
    A : [rank, in_dim]   from {key}.lora_A.weight
    B : [out_dim, rank]  from {key}.lora_B.weight
    alpha : scalar       from {key}.alpha (falls back to rank)
    scale : float        user-supplied LoRA strength

All 4 LoRAs in the Darwin-Image-v1 stack have been verified to use this
ai-toolkit standard format with 480 keys each (all `layers.0..29` covered).

Usage:
    from darwin_image.pipeline.manual_fuse import (
        download_and_fuse, load_lora_state_dict, fuse_into_transformer)

    report = download_and_fuse(
        pipe.transformer,
        loras=[
            ("Shakker-Labs/AWPortrait-Z", "AWPortrait-Z.safetensors", 0.7),
            ...
        ],
        token=HF_TOKEN,
    )
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

import torch


LORA_PREFIX = "diffusion_model."


def load_lora_state_dict(path: str) -> Dict[str, torch.Tensor]:
    """Load a LoRA state_dict from a local .safetensors file."""
    from safetensors.torch import load_file
    return load_file(path)


def strip_prefix(key: str) -> str:
    """Strip the `diffusion_model.` prefix added by ai-toolkit trainers."""
    if key.startswith(LORA_PREFIX):
        return key[len(LORA_PREFIX):]
    return key


def _resolve_target_weight_key(base_key: str) -> str:
    """Given e.g. 'layers.0.attention.to_q', return 'layers.0.attention.to_q.weight'."""
    return base_key + ".weight"


def fuse_into_transformer(
    transformer: torch.nn.Module,
    lora_sd: Dict[str, torch.Tensor],
    scale: float = 1.0,
    verbose: bool = True,
) -> Dict:
    """Directly fuse a LoRA state_dict into a transformer's parameters.

    Iterates the LoRA state_dict, groups lora_A/lora_B/alpha triples by base
    module name, and adds `(B @ A) * (alpha/rank) * scale` to the matching
    transformer weight in-place.

    Args:
        transformer: nn.Module with named_parameters (e.g. pipe.transformer).
        lora_sd: Loaded LoRA state_dict.
        scale: Multiplier on the LoRA delta.
        verbose: Print progress.

    Returns:
        {'fused': N, 'missing': M, 'skipped': K, 'samples': [...]}
    """
    # Index base transformer parameters by their fully qualified name
    base_params = dict(transformer.named_parameters())

    # Group lora_A, lora_B, alpha by their common base key
    # e.g. "layers.0.attention.to_q" -> {"A": tensor, "B": tensor, "alpha": 16}
    groups: Dict[str, Dict[str, torch.Tensor]] = {}

    for raw_key, tensor in lora_sd.items():
        key = strip_prefix(raw_key)
        if ".lora_A.weight" in key:
            base = key.replace(".lora_A.weight", "")
            groups.setdefault(base, {})["A"] = tensor
        elif ".lora_B.weight" in key:
            base = key.replace(".lora_B.weight", "")
            groups.setdefault(base, {})["B"] = tensor
        elif key.endswith(".alpha"):
            base = key.replace(".alpha", "")
            groups.setdefault(base, {})["alpha"] = tensor
        elif ".lora_down.weight" in key:  # kohya-style alternative naming
            base = key.replace(".lora_down.weight", "")
            groups.setdefault(base, {})["A"] = tensor
        elif ".lora_up.weight" in key:
            base = key.replace(".lora_up.weight", "")
            groups.setdefault(base, {})["B"] = tensor

    stats = {
        "fused": 0,
        "missing": 0,
        "skipped_incomplete": 0,
        "lora_modules": len(groups),
        "missing_keys": [],
        "samples": [],
    }

    with torch.no_grad():
        for base_key, parts in groups.items():
            if "A" not in parts or "B" not in parts:
                stats["skipped_incomplete"] += 1
                continue

            target_key = _resolve_target_weight_key(base_key)
            if target_key not in base_params:
                stats["missing"] += 1
                if len(stats["missing_keys"]) < 5:
                    stats["missing_keys"].append(target_key)
                continue

            A = parts["A"].float()  # [rank, in_dim]
            B = parts["B"].float()  # [out_dim, rank]

            if A.ndim != 2 or B.ndim != 2 or A.shape[0] != B.shape[1]:
                stats["skipped_incomplete"] += 1
                continue

            rank = A.shape[0]
            if "alpha" in parts:
                alpha_t = parts["alpha"]
                try:
                    alpha_val = float(alpha_t.item())
                except Exception:
                    alpha_val = float(alpha_t)
            else:
                alpha_val = float(rank)

            # Delta: [out_dim, in_dim]
            delta = (B @ A) * (alpha_val / max(rank, 1)) * scale

            target = base_params[target_key]
            if target.shape != delta.shape:
                stats["skipped_incomplete"] += 1
                if verbose and stats["skipped_incomplete"] <= 3:
                    print(f"  [manual_fuse] shape mismatch {target_key}: "
                          f"{tuple(target.shape)} vs delta {tuple(delta.shape)}")
                continue

            target.data.add_(delta.to(device=target.device, dtype=target.dtype))
            stats["fused"] += 1
            if len(stats["samples"]) < 3:
                stats["samples"].append({
                    "key": target_key,
                    "rank": rank,
                    "alpha": alpha_val,
                    "delta_norm": float(delta.norm().item()),
                })

    if verbose:
        print(f"  [manual_fuse] fused={stats['fused']} missing={stats['missing']} "
              f"skipped={stats['skipped_incomplete']} (out of {stats['lora_modules']} modules)")

    return stats


def download_and_fuse(
    transformer: torch.nn.Module,
    loras: List[Tuple[str, str, float]],
    token: Optional[str] = None,
    verbose: bool = True,
) -> Dict:
    """Convenience: download each LoRA file from HF and fuse it sequentially.

    Args:
        transformer: Target module (pipe.transformer for Z-Image).
        loras: List of (repo_id, weight_filename, scale) tuples.
        token: HF token for private repo access.
        verbose: Print progress.

    Returns:
        {'loras_applied': [...], 'loras_skipped': [...]}
    """
    from huggingface_hub import hf_hub_download

    report = {"loras_applied": [], "loras_skipped": []}

    for repo_id, weight_name, scale in loras:
        if verbose:
            print(f"\n  [manual_fuse] {repo_id}/{weight_name} @ scale={scale}")
        try:
            local_path = hf_hub_download(
                repo_id=repo_id,
                filename=weight_name,
                token=token,
            )
            lora_sd = load_lora_state_dict(local_path)
            stats = fuse_into_transformer(transformer, lora_sd, scale=scale, verbose=verbose)
            # Release LoRA state dict memory
            del lora_sd
            import gc; gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            if stats["fused"] == 0:
                report["loras_skipped"].append({
                    "repo_id": repo_id,
                    "weight_name": weight_name,
                    "reason": f"no modules matched (lora_modules={stats['lora_modules']}, missing={stats['missing']})",
                })
            else:
                report["loras_applied"].append({
                    "repo_id": repo_id,
                    "weight_name": weight_name,
                    "scale": scale,
                    "fused": stats["fused"],
                    "lora_modules": stats["lora_modules"],
                })
        except Exception as exc:
            if verbose:
                print(f"  [manual_fuse] FAIL: {exc}")
            report["loras_skipped"].append({
                "repo_id": repo_id,
                "weight_name": weight_name,
                "reason": str(exc),
            })

    return report
