"""Darwin Image pipeline package.

Integrates Z-Image Turbo with Darwin-4B-David VLM for AETHER metacognitive
image generation.
"""

from .config import AetherConfig, LoraConfig, JudgeConfig, PipelineConfig
from .darwin_pipeline import DarwinZImagePipeline
from .korean_inpaint import render_text_with_mask, detect_korean_in_prompt
from .vlm_judge import DarwinJudge
from .aether import run_aether
from .mti import apply_mti_hook, remove_mti_hook

__all__ = [
    "AetherConfig",
    "LoraConfig",
    "JudgeConfig",
    "PipelineConfig",
    "DarwinZImagePipeline",
    "render_text_with_mask",
    "detect_korean_in_prompt",
    "DarwinJudge",
    "run_aether",
    "apply_mti_hook",
    "remove_mti_hook",
]

__version__ = "1.0.0"
