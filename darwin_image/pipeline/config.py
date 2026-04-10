"""Configuration dataclasses for Darwin Image pipeline."""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class LoraConfig:
    """Single LoRA adapter configuration."""
    repo_id: str
    scale: float = 1.0
    adapter_name: Optional[str] = None
    weight_file: Optional[str] = None
    commit_sha: Optional[str] = None


# Default LoRA stack for Darwin-Image-v1
DEFAULT_LORA_STACK: List[LoraConfig] = [
    LoraConfig(repo_id="Shakker-Labs/AWPortrait-Z", scale=0.7, adapter_name="portrait"),
    LoraConfig(repo_id="qqnyanddld/nsfw-z-image-lora", scale=0.5, adapter_name="nsfw"),
    LoraConfig(repo_id="renderartist/Technically-Color-Z-Image-Turbo", scale=0.4, adapter_name="color"),
    LoraConfig(repo_id="wcde/Z-Image-Turbo-DeJPEG-Lora", scale=0.3, adapter_name="dejpeg"),
]


@dataclass
class JudgeConfig:
    """Darwin-4B-David VLM judge configuration.

    When `model_id` points to the unified Darwin-Image-v1 repo, set
    `subfolder="vlm_judge"` to load the bundled Darwin-4B-David. Otherwise
    leave `subfolder=None` to load the standalone Darwin-4B-David repo.
    """
    model_id: str = "FINAL-Bench/Darwin-Image-v1"
    subfolder: Optional[str] = "vlm_judge"
    fallback_model_id: str = "FINAL-Bench/Darwin-4B-David"
    dtype: str = "bfloat16"
    device: str = "cuda"
    max_new_tokens: int = 512
    temperature: float = 0.3
    load_in_4bit: bool = False


@dataclass
class AetherConfig:
    """AETHER metacognitive loop configuration."""
    max_iter: int = 3
    threshold: float = 8.0
    enable_mti: bool = False
    enable_vlm_enhance: bool = True
    enable_vlm_judge: bool = True
    seed_increment: int = 1
    keep_all_iterations: bool = True
    # Per-iteration override for seed-only variation
    seed_only_retry: bool = False


@dataclass
class PipelineConfig:
    """Top-level Darwin Image pipeline configuration.

    Defaults tuned for Z-Image Turbo (8-step distilled model). The Tongyi-MAI
    official recommendation is guidance_scale=0.0 (CFG disabled) and 9 sampler
    steps. Using higher CFG or strong negative prompts darkens the output and
    breaks the distilled flow matching objective.
    """
    base_model: str = "FINAL-Bench/Darwin-Image-v1"
    fallback_base_model: str = "Tongyi-MAI/Z-Image-Turbo"
    num_inference_steps: int = 9
    guidance_scale: float = 0.0  # Z-Image Turbo requires CFG disabled
    height: int = 1024
    width: int = 1024
    negative_prompt: str = ""  # Turbo models ignore negative prompts at CFG=0
    inpaint_strength: float = 0.35
    inpaint_steps: int = 12
    font_path: str = "assets/NotoSansKR-Bold.ttf"
    disable_safety: bool = True


@dataclass
class GenerationResult:
    """Result of a single AETHER generation run."""
    final_image: object = None  # PIL.Image
    iterations: List[dict] = field(default_factory=list)
    best_iter: int = 0
    final_prompt: str = ""
    korean_texts: List[dict] = field(default_factory=list)
    total_time_sec: float = 0.0
