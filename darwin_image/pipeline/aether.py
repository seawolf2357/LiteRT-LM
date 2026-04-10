"""AETHER metacognitive loop for image generation.

Loop structure:
    enhanced = VLM.enhance(user_prompt)
    for i in range(max_iter):
        image = DiT(enhanced, seed=seed+i)
        scores = VLM.score(image, user_prompt)
        if scores.overall >= threshold:
            break
        enhanced = VLM.critique(image, user_prompt, enhanced, issues=scores.issues)
    return best

This implements the VLM-in-the-Loop pattern from Reflect-DiT (ICCV 2025)
and LumiGen's IPPA+IVFR approach, adapted for Darwin's AETHER philosophy.
"""

import gc
import time
from typing import Callable, Dict, List, Optional

import torch
from PIL import Image

from .config import AetherConfig, GenerationResult
from .darwin_pipeline import DarwinZImagePipeline
from .vlm_judge import DarwinJudge


def run_aether(
    user_prompt: str,
    pipe: DarwinZImagePipeline,
    judge: Optional[DarwinJudge] = None,
    config: Optional[AetherConfig] = None,
    seed: int = 42,
    progress_callback: Optional[Callable[[int, Dict], None]] = None,
    **gen_kwargs,
) -> GenerationResult:
    """Run the AETHER metacognitive generation loop.

    Args:
        user_prompt: Raw user request (may contain Korean).
        pipe: DarwinZImagePipeline instance (Z-Image + Korean inpainting).
        judge: DarwinJudge instance (VLM). Optional — skips loop if None.
        config: AetherConfig with max_iter, threshold, etc.
        seed: Base random seed (each iteration uses seed + i * seed_increment).
        progress_callback: Optional callable(iter_idx, state) for UI streaming.
        **gen_kwargs: Extra kwargs passed to pipe() (steps, guidance, size).

    Returns:
        GenerationResult with final_image, iterations history, best_iter.
    """
    cfg = config or AetherConfig()
    start_time = time.time()
    history: List[Dict] = []

    # Step 1: VLM prompt enhancement
    if judge is not None and cfg.enable_vlm_enhance:
        try:
            enhanced, korean_texts = judge.enhance(user_prompt)
        except Exception as exc:
            print(f"[AETHER] enhance failed, using raw prompt: {exc}")
            from .korean_inpaint import detect_korean_in_prompt
            korean_texts, scene = detect_korean_in_prompt(user_prompt)
            enhanced = scene
    else:
        from .korean_inpaint import detect_korean_in_prompt
        korean_texts, enhanced = detect_korean_in_prompt(user_prompt)

    current_prompt = enhanced

    # Step 2: iterative generation + judging
    for i in range(cfg.max_iter):
        iter_seed = seed + (i * cfg.seed_increment)

        if progress_callback:
            progress_callback(i, {"stage": "generating", "prompt": current_prompt, "seed": iter_seed})

        # Generate
        try:
            image = pipe(
                prompt=current_prompt,
                korean_texts=korean_texts,
                seed=iter_seed,
                **gen_kwargs,
            )
        except Exception as exc:
            print(f"[AETHER] generation failed at iter {i}: {exc}")
            if history:
                break
            raise

        # Free cache between stages
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # Judge
        if judge is not None and cfg.enable_vlm_judge:
            if progress_callback:
                progress_callback(i, {"stage": "judging", "prompt": current_prompt, "image": image})
            try:
                scores = judge.score(image, user_prompt)
            except Exception as exc:
                print(f"[AETHER] score failed at iter {i}: {exc}")
                scores = {"overall": 7.0, "issues": [f"judge error: {exc}"]}
        else:
            scores = {"overall": 10.0, "issues": []}  # skip loop

        entry = {
            "iter": i,
            "image": image,
            "scores": scores,
            "prompt": current_prompt,
            "seed": iter_seed,
        }
        history.append(entry)

        if progress_callback:
            progress_callback(i, {"stage": "scored", **entry})

        overall = float(scores.get("overall", 0))
        if overall >= cfg.threshold:
            break

        # Refine prompt for next iteration (unless this was the last)
        if i < cfg.max_iter - 1 and judge is not None:
            if progress_callback:
                progress_callback(i, {"stage": "refining", "prev_prompt": current_prompt})
            try:
                current_prompt = judge.critique(
                    image,
                    user_prompt,
                    current_prompt,
                    issues=scores.get("issues", []),
                )
            except Exception as exc:
                print(f"[AETHER] critique failed at iter {i}: {exc}")
                # keep previous prompt, just bump seed

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()

    # Pick best iteration
    best_idx = max(range(len(history)), key=lambda k: history[k]["scores"].get("overall", 0))
    best = history[best_idx]

    total_time = time.time() - start_time

    return GenerationResult(
        final_image=best["image"],
        iterations=history,
        best_iter=best_idx,
        final_prompt=best["prompt"],
        korean_texts=korean_texts,
        total_time_sec=total_time,
    )
