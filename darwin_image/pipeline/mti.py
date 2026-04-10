"""Minimal Test-Time Intervention (MTI) for DiT models.

Based on arxiv 2510.13940: "Minimal Test-Time Intervention for Enhanced
Reasoning in Large Language Models" — extended to diffusion transformers.

Core idea: during inference, compute per-token entropy and apply guidance
scale boost ONLY where entropy exceeds a percentile threshold. For DiT,
this translates to per-step entropy on attention logits during denoising.

NOTE: Z-Image Turbo is 8-step distilled. MTI was designed for 30+ step
models, so it's shipped as an opt-in feature with a UI toggle. Quality
effects on few-step distilled models are currently unverified.
"""

from dataclasses import dataclass
from typing import Optional

import torch


@dataclass
class MTIConfig:
    enabled: bool = False
    entropy_percentile: float = 0.75  # Top 25% entropy tokens get boost
    cfg_boost: float = 1.5            # Multiplicative boost on guidance scale
    apply_to_steps: Optional[tuple] = None  # e.g. (4, 8) for late steps only


_original_forward_cache = {}


def apply_mti_hook(transformer, config: MTIConfig):
    """Monkey-patch transformer forward to apply entropy-gated CFG boost.

    This is a lightweight wrapper that intercepts the attention output and
    scales selected positions. It is a no-op if config.enabled is False.

    Args:
        transformer: The DiT transformer module (e.g. pipe.transformer).
        config: MTIConfig controlling the intervention.

    Returns:
        Handle that can be passed to remove_mti_hook to restore original.
    """
    if not config.enabled:
        return None

    module_id = id(transformer)
    if module_id in _original_forward_cache:
        return module_id  # already hooked

    original_forward = transformer.forward
    _original_forward_cache[module_id] = original_forward

    def mti_forward(*args, **kwargs):
        out = original_forward(*args, **kwargs)
        # Boost high-entropy token outputs
        if isinstance(out, tuple):
            hidden = out[0]
        else:
            hidden = out
        if torch.is_tensor(hidden) and hidden.dim() >= 2:
            with torch.no_grad():
                # Compute per-token entropy proxy: std across channels
                ent = hidden.float().std(dim=-1)
                # Flatten to 1D per sample for percentile
                thresh = torch.quantile(ent.flatten(), config.entropy_percentile)
                mask = (ent > thresh).unsqueeze(-1).to(hidden.dtype)
                boosted = hidden * (1.0 + (config.cfg_boost - 1.0) * mask)
            if isinstance(out, tuple):
                return (boosted,) + out[1:]
            return boosted
        return out

    transformer.forward = mti_forward
    return module_id


def remove_mti_hook(transformer, handle):
    """Restore the original forward method."""
    if handle is None:
        return
    module_id = id(transformer)
    if module_id in _original_forward_cache:
        transformer.forward = _original_forward_cache.pop(module_id)
