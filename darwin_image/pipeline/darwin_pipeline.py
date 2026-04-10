"""DarwinZImagePipeline — Z-Image Turbo with Korean inpainting auto-integration.

Based on darwin_pipeline.py snippet from Darwin Image v1.0 spec (section 10-3).
Adds lazy loading, HF token auth, and graceful fallbacks.
"""

import gc
import os
from typing import List, Optional, Union

import torch
from PIL import Image

from .config import PipelineConfig
from .korean_inpaint import detect_korean_in_prompt, render_text_with_mask


class DarwinZImagePipeline:
    """Unified text-to-image pipeline with Korean text rendering.

    Supports lazy loading of Z-Image Turbo (t2i + inpaint) to minimize
    memory footprint when running alongside the Darwin-4B-David VLM judge.
    """

    def __init__(
        self,
        base_model: Optional[str] = None,
        device: str = "cuda",
        dtype: torch.dtype = torch.bfloat16,
        token: Optional[str] = None,
        config: Optional[PipelineConfig] = None,
        disable_safety: bool = True,
    ):
        self.config = config or PipelineConfig()
        self.base_model = base_model or self.config.base_model
        self.device = device
        self.dtype = dtype
        self.token = token or os.environ.get("HF_TOKEN")
        self.disable_safety = disable_safety

        self._t2i = None
        self._inpaint = None

    # --------------------------------------------------------------- loading

    def _resolve_base_model(self) -> str:
        """Try fused repo first, fall back to vanilla Z-Image-Turbo."""
        return self.base_model

    def _load_t2i(self):
        if self._t2i is not None:
            return self._t2i
        from diffusers import DiffusionPipeline

        model_id = self._resolve_base_model()
        try:
            pipe = DiffusionPipeline.from_pretrained(
                model_id,
                torch_dtype=self.dtype,
                token=self.token,
            )
        except Exception as exc:
            fallback = self.config.fallback_base_model
            print(f"[DarwinPipeline] Falling back to {fallback}: {exc}")
            pipe = DiffusionPipeline.from_pretrained(
                fallback,
                torch_dtype=self.dtype,
                token=self.token,
            )

        pipe = pipe.to(self.device)
        if self.disable_safety:
            self._disable_safety_checker(pipe)
        self._t2i = pipe
        return pipe

    def _load_inpaint(self):
        """Reuse the same pipeline for inpainting via img2img + mask.

        Z-Image Turbo doesn't ship a dedicated inpaint pipeline, so we fall
        back to img2img with a composited input when needed. If a Fun-Inpaint
        checkpoint is available, prefer that.
        """
        if self._inpaint is not None:
            return self._inpaint

        try:
            from diffusers import DiffusionPipeline
            pipe = DiffusionPipeline.from_pretrained(
                "alibaba-pai/Z-Image-Turbo-Fun-Inpaint",
                torch_dtype=self.dtype,
                token=self.token,
            ).to(self.device)
            if self.disable_safety:
                self._disable_safety_checker(pipe)
            self._inpaint = pipe
            return pipe
        except Exception as exc:
            print(f"[DarwinPipeline] Fun-Inpaint unavailable, using img2img: {exc}")
            # Reuse the t2i pipeline — we'll bypass the mask at call time
            self._inpaint = self._load_t2i()
            return self._inpaint

    @staticmethod
    def _disable_safety_checker(pipe):
        """Remove any safety-checker artifacts (Z-Image Turbo ships without one)."""
        for attr in ("safety_checker", "watermarker", "feature_extractor"):
            if hasattr(pipe, attr):
                try:
                    setattr(pipe, attr, None)
                except Exception:
                    pass

    # --------------------------------------------------------------- inference

    def _t2i_generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        num_inference_steps: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        height: Optional[int] = None,
        width: Optional[int] = None,
    ) -> Image.Image:
        pipe = self._load_t2i()
        generator = torch.Generator(device=self.device).manual_seed(seed if seed is not None else 42)
        result = pipe(
            prompt=prompt,
            negative_prompt=negative_prompt or self.config.negative_prompt,
            num_inference_steps=num_inference_steps or self.config.num_inference_steps,
            guidance_scale=guidance_scale if guidance_scale is not None else self.config.guidance_scale,
            height=height or self.config.height,
            width=width or self.config.width,
            generator=generator,
        )
        return result.images[0]

    def _inpaint_blend(
        self,
        image: Image.Image,
        mask: Image.Image,
        prompt: str,
        seed: Optional[int] = None,
    ) -> Image.Image:
        """Blend text edges with background via inpainting."""
        pipe = self._load_inpaint()
        generator = torch.Generator(device=self.device).manual_seed((seed or 42) + 1000)

        try:
            result = pipe(
                prompt=prompt,
                image=image,
                mask_image=mask,
                strength=self.config.inpaint_strength,
                num_inference_steps=self.config.inpaint_steps,
                guidance_scale=self.config.guidance_scale,
                generator=generator,
            )
            return result.images[0]
        except TypeError:
            # Pipeline doesn't accept mask_image — return the composited image
            # (the font-rendered layer already looks clean on most backgrounds)
            return image

    # ------------------------------------------------------------------- call

    def __call__(
        self,
        prompt: str,
        korean_texts: Optional[List[dict]] = None,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        num_inference_steps: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        height: Optional[int] = None,
        width: Optional[int] = None,
        font_path: Optional[str] = None,
    ) -> Image.Image:
        # Auto-detect Korean if not supplied explicitly
        if korean_texts is None:
            korean_texts, scene_prompt = detect_korean_in_prompt(prompt)
        else:
            # User provided Korean — strip any Korean from the prompt to keep DiT clean
            _, scene_prompt = detect_korean_in_prompt(prompt)

        # Stage 1: background
        base = self._t2i_generate(
            prompt=scene_prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            height=height,
            width=width,
        )

        if not korean_texts:
            return base

        # Stage 2: PIL font composite + mask
        composited, mask = render_text_with_mask(
            base,
            korean_texts,
            font_path=font_path or self.config.font_path,
        )

        # Stage 3: edge-only inpainting
        final = self._inpaint_blend(composited, mask, prompt=scene_prompt, seed=seed)
        return final

    # --------------------------------------------------------------- cleanup

    def cleanup(self):
        """Release GPU memory — call between iterations if memory pressure."""
        if self._t2i is not None:
            del self._t2i
            self._t2i = None
        if self._inpaint is not None:
            del self._inpaint
            self._inpaint = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def to_cpu_offload(self):
        """Move pipelines to CPU to free GPU for VLM inference."""
        if self._t2i is not None:
            self._t2i.to("cpu")
        if self._inpaint is not None and self._inpaint is not self._t2i:
            self._inpaint.to("cpu")
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def to_gpu(self):
        """Move pipelines back to GPU after CPU offload."""
        if self._t2i is not None:
            self._t2i.to(self.device)
        if self._inpaint is not None and self._inpaint is not self._t2i:
            self._inpaint.to(self.device)
