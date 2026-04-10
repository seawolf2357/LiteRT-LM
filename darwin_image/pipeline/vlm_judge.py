"""Darwin-4B-David VLM wrapper: prompt enhancement + image quality judging.

Darwin-4B-David is a Gemma4 multimodal model (Gemma4ForConditionalGeneration)
with `<|image|>` chat template tokens. It handles both text generation
(prompt enhancement) and vision-language scoring (image critique).

Role 1: enhance(prompt) → English-enhanced prompt + extracted Korean strings
Role 2: score(image, prompt) → {overall, fidelity, composition, face, technical}
Role 3: critique(image, prompt, prev) → refined prompt addressing flaws
"""

import gc
import json
import os
import re
from typing import Dict, List, Optional, Tuple

import torch
from PIL import Image

from .config import JudgeConfig


SYSTEM_PROMPT_ENHANCE = """You are an expert text-to-image prompt engineer for the Z-Image Turbo diffusion model.
Your job is to take a user's raw request (in Korean or English) and rewrite it as a rich, detailed English prompt that will produce the best possible image.

Rules:
1. If the user's request contains Korean text inside quotes (e.g. "봄의 서울"), that text MUST be rendered as Korean typography in the final image. Extract these quoted Korean strings.
2. The main English prompt should describe the SCENE, not the text. Do NOT mention "text", "sign", "poster", "writing" — those cause DiT hallucinations.
3. Include: subject, lighting, composition, style, mood, color palette, camera details.
4. Output ONLY valid JSON with this exact schema:
{"enhanced_prompt": "<detailed English scene description>", "korean_texts": [{"text": "<string>", "position": "top|center|bottom"}]}

Examples:
Input: 벚꽃 남산타워 포스터 "봄의 서울"
Output: {"enhanced_prompt": "Cinematic photograph of Namsan Tower in Seoul surrounded by blooming cherry blossoms, golden hour lighting, soft pink petals falling, sharp focus, 8k detail, shallow depth of field, photorealistic", "korean_texts": [{"text": "봄의 서울", "position": "bottom"}]}

Input: cute cat drinking coffee
Output: {"enhanced_prompt": "Adorable fluffy kitten sitting at a wooden cafe table with a tiny latte cup, warm morning sunlight through window, bokeh background, pastel color palette, shallow depth of field, photorealistic portrait", "korean_texts": []}"""

SYSTEM_PROMPT_JUDGE = """You are a strict image quality judge. Evaluate the given image against the user's original prompt.

Score on 5 dimensions (1-10):
1. prompt_fidelity: Does the image match what was asked?
2. composition: Is framing, balance, rule of thirds good?
3. faces_hands: Are faces/hands anatomically correct? (10 if N/A)
4. technical: Sharpness, lighting, color, absence of artifacts
5. aesthetic: Overall visual appeal

Also list concrete issues you observe.

Output ONLY valid JSON:
{"fidelity": <int>, "composition": <int>, "faces_hands": <int>, "technical": <int>, "aesthetic": <int>, "overall": <float>, "issues": ["<issue 1>", "<issue 2>"]}"""

SYSTEM_PROMPT_CRITIQUE = """You are a prompt refinement expert. Given:
1. The user's original intent
2. The previous DiT prompt that was used
3. An image that scored poorly
4. A list of issues

Rewrite the prompt to fix the issues while preserving the user's intent. Add specific descriptors that address each issue (e.g. "detailed face, sharp eyes" for face problems, "natural five fingers" for hand issues).

Output ONLY the refined English prompt as plain text, no JSON, no explanations."""


def _parse_json_loose(text: str) -> Optional[dict]:
    """Extract JSON from model output, tolerant of surrounding text."""
    if not text:
        return None
    # Try straight parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Extract first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


class DarwinJudge:
    """Wraps Darwin-4B-David for prompt enhancement and image judging."""

    def __init__(
        self,
        config: Optional[JudgeConfig] = None,
        token: Optional[str] = None,
    ):
        self.config = config or JudgeConfig()
        self.token = token or os.environ.get("HF_TOKEN")
        self._model = None
        self._processor = None
        self._tokenizer = None

    # --------------------------------------------------------------- loading

    def load(self):
        if self._model is not None:
            return

        from transformers import AutoProcessor, AutoTokenizer

        dtype = getattr(torch, self.config.dtype)

        quant_kwargs = {}
        if self.config.load_in_4bit:
            from transformers import BitsAndBytesConfig
            quant_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=dtype,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
            )

        # Build list of (model_id, subfolder) candidates to try in order
        candidates = [(self.config.model_id, self.config.subfolder)]
        if self.config.fallback_model_id and self.config.fallback_model_id != self.config.model_id:
            candidates.append((self.config.fallback_model_id, None))

        last_exc = None
        for model_id, subfolder in candidates:
            sub_kwargs = {}
            if subfolder:
                sub_kwargs["subfolder"] = subfolder
            location_desc = f"{model_id}" + (f"/{subfolder}" if subfolder else "")
            print(f"[DarwinJudge] Loading VLM from {location_desc}...")

            try:
                # Try Gemma4ForConditionalGeneration first
                try:
                    from transformers import Gemma4ForConditionalGeneration
                    self._model = Gemma4ForConditionalGeneration.from_pretrained(
                        model_id,
                        torch_dtype=dtype,
                        device_map=self.config.device,
                        token=self.token,
                        **sub_kwargs,
                        **quant_kwargs,
                    )
                except (ImportError, AttributeError):
                    from transformers import AutoModelForCausalLM
                    self._model = AutoModelForCausalLM.from_pretrained(
                        model_id,
                        torch_dtype=dtype,
                        device_map=self.config.device,
                        trust_remote_code=True,
                        token=self.token,
                        **sub_kwargs,
                        **quant_kwargs,
                    )

                try:
                    self._processor = AutoProcessor.from_pretrained(
                        model_id,
                        token=self.token,
                        trust_remote_code=True,
                        **sub_kwargs,
                    )
                except Exception as exc:
                    print(f"[DarwinJudge] AutoProcessor failed ({exc}), using tokenizer only")
                    self._processor = None

                self._tokenizer = AutoTokenizer.from_pretrained(
                    model_id,
                    token=self.token,
                    trust_remote_code=True,
                    **sub_kwargs,
                )
                print(f"[DarwinJudge] ✓ VLM loaded from {location_desc}")
                return
            except Exception as exc:
                last_exc = exc
                print(f"[DarwinJudge] Failed to load from {location_desc}: {exc}")
                self._model = None
                self._processor = None
                self._tokenizer = None
                continue

        raise RuntimeError(
            f"Could not load VLM from any candidate: {candidates}. Last error: {last_exc}"
        )

    def cleanup(self):
        if self._model is not None:
            del self._model
            self._model = None
        if self._processor is not None:
            del self._processor
            self._processor = None
        if self._tokenizer is not None:
            del self._tokenizer
            self._tokenizer = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def to_cpu_offload(self):
        if self._model is not None:
            self._model.to("cpu")
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def to_gpu(self):
        if self._model is not None:
            self._model.to(self.config.device)

    # ---------------------------------------------------------- core generate

    def _generate_text(
        self,
        system: str,
        user_content,  # str or list of content blocks
        max_new_tokens: Optional[int] = None,
    ) -> str:
        self.load()

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content if isinstance(user_content, list) else [{"type": "text", "text": user_content}]},
        ]

        if self._processor is not None:
            try:
                inputs = self._processor.apply_chat_template(
                    messages,
                    add_generation_prompt=True,
                    tokenize=True,
                    return_dict=True,
                    return_tensors="pt",
                ).to(self._model.device)
            except Exception as exc:
                print(f"[DarwinJudge] processor.apply_chat_template failed: {exc}")
                inputs = None
        else:
            inputs = None

        if inputs is None:
            # Text-only fallback
            text_only = user_content if isinstance(user_content, str) else " ".join(
                c.get("text", "") for c in user_content if c.get("type") == "text"
            )
            prompt_str = f"{system}\n\nUser: {text_only}\nAssistant:"
            inputs = self._tokenizer(prompt_str, return_tensors="pt").to(self._model.device)

        with torch.inference_mode():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens or self.config.max_new_tokens,
                temperature=self.config.temperature,
                do_sample=self.config.temperature > 0,
                pad_token_id=self._tokenizer.eos_token_id if self._tokenizer else None,
            )

        # Slice off the prompt portion
        input_len = inputs["input_ids"].shape[1] if "input_ids" in inputs else 0
        new_tokens = output_ids[0][input_len:]
        tokenizer = self._tokenizer or (self._processor.tokenizer if self._processor else None)
        text = tokenizer.decode(new_tokens, skip_special_tokens=True)
        return text.strip()

    # -------------------------------------------------------- high-level APIs

    def enhance(self, prompt: str) -> Tuple[str, List[Dict]]:
        """Enhance user prompt and extract Korean strings.

        Returns (enhanced_english_prompt, korean_texts).
        Falls back to heuristic extraction if the model output is unparseable.
        """
        try:
            raw = self._generate_text(SYSTEM_PROMPT_ENHANCE, prompt, max_new_tokens=384)
            parsed = _parse_json_loose(raw)
            if parsed and "enhanced_prompt" in parsed:
                return (
                    parsed.get("enhanced_prompt", prompt),
                    parsed.get("korean_texts", []),
                )
        except Exception as exc:
            print(f"[DarwinJudge] enhance failed: {exc}")

        # Fallback: use heuristic Korean detection + append quality modifiers
        from .korean_inpaint import detect_korean_in_prompt
        korean_texts, scene = detect_korean_in_prompt(prompt)
        enhanced = f"{scene}, cinematic, highly detailed, 8k, photorealistic, sharp focus"
        return enhanced, korean_texts

    def score(self, image: Image.Image, original_prompt: str) -> Dict:
        """Score an image against its original prompt.

        Returns dict with 'overall' (float) and component scores.
        """
        user_content = [
            {"type": "image", "image": image},
            {"type": "text", "text": f"Original user prompt: {original_prompt}\n\nEvaluate this image and return JSON scores."},
        ]
        try:
            raw = self._generate_text(SYSTEM_PROMPT_JUDGE, user_content, max_new_tokens=384)
            parsed = _parse_json_loose(raw)
            if parsed:
                # Compute overall if missing
                if "overall" not in parsed:
                    components = [
                        parsed.get("fidelity", 5),
                        parsed.get("composition", 5),
                        parsed.get("faces_hands", 10),
                        parsed.get("technical", 5),
                        parsed.get("aesthetic", 5),
                    ]
                    parsed["overall"] = round(sum(components) / len(components), 2)
                parsed.setdefault("issues", [])
                return parsed
        except Exception as exc:
            print(f"[DarwinJudge] score failed: {exc}")

        # Conservative fallback: neutral score with no info
        return {
            "fidelity": 7,
            "composition": 7,
            "faces_hands": 7,
            "technical": 7,
            "aesthetic": 7,
            "overall": 7.0,
            "issues": ["VLM scoring unavailable, using fallback"],
        }

    def critique(
        self,
        image: Image.Image,
        original_prompt: str,
        previous_prompt: str,
        issues: Optional[List[str]] = None,
    ) -> str:
        """Refine the prompt based on observed image flaws."""
        issues_text = "\n".join(f"- {i}" for i in (issues or []))
        user_content = [
            {"type": "image", "image": image},
            {
                "type": "text",
                "text": (
                    f"Original user intent: {original_prompt}\n\n"
                    f"Previous DiT prompt that produced this image:\n{previous_prompt}\n\n"
                    f"Observed issues:\n{issues_text or '- low overall quality'}\n\n"
                    f"Rewrite the prompt to fix these issues."
                ),
            },
        ]
        try:
            refined = self._generate_text(SYSTEM_PROMPT_CRITIQUE, user_content, max_new_tokens=256)
            # Clean up any markdown/quotes
            refined = refined.strip().strip('"').strip("'").strip("`")
            if len(refined) > 20:
                return refined
        except Exception as exc:
            print(f"[DarwinJudge] critique failed: {exc}")

        # Fallback: append issue-targeted keywords
        fallback_keywords = []
        for issue in issues or []:
            low = issue.lower()
            if "face" in low:
                fallback_keywords.append("detailed face, sharp eyes, symmetric features")
            if "hand" in low or "finger" in low:
                fallback_keywords.append("natural hands, five fingers, accurate anatomy")
            if "blur" in low:
                fallback_keywords.append("sharp focus, crisp details")
            if "light" in low or "exposure" in low:
                fallback_keywords.append("balanced lighting, proper exposure")
        extras = ", ".join(fallback_keywords) if fallback_keywords else "higher quality, more detail"
        return f"{previous_prompt}, {extras}"
