"""3-Stage Korean text rendering with edge-only inpainting.

Stage 1: Z-Image generates clean background (text-related words removed)
Stage 2: PIL renders Korean text with shadow/outline/font → edge mask
Stage 3: Z-Image inpainting blends only the text edges with background
"""

import re
from typing import List, Optional, Tuple, Dict

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


# Regex: quoted Korean-containing strings
KOREAN_QUOTE_RE = re.compile(r'"([^"]*[\uac00-\ud7a3]+[^"]*)"')
KOREAN_CHAR_RE = re.compile(r'[\uac00-\ud7a3]')

# Words that confuse DiT into generating broken pseudo-text
TEXT_REMOVAL_WORDS = [
    "text", "sign", "menu", "letter", "letters", "word", "words",
    "title", "heading", "caption", "label", "typography", "font",
    "poster text", "written", "writing", "inscription",
    "포스터", "간판", "메뉴", "글자", "문자", "제목", "캡션",
]


def detect_korean_in_prompt(prompt: str) -> Tuple[List[Dict], str]:
    """Extract quoted Korean strings and return cleaned scene prompt.

    Returns:
        (korean_texts, scene_prompt)
        korean_texts: [{"text": "봄의 서울", "position": "auto", "size": "auto"}]
        scene_prompt: prompt with quotes and text-related words removed
    """
    korean_texts = []
    for match in KOREAN_QUOTE_RE.finditer(prompt):
        text = match.group(1)
        korean_texts.append({
            "text": text,
            "position": "auto",
            "size": "auto",
        })

    # Also catch bare Korean sequences (not in quotes)
    if not korean_texts:
        bare = KOREAN_CHAR_RE.findall(prompt)
        if bare:
            # Grab contiguous Korean spans
            span_re = re.compile(r'[\uac00-\ud7a3][\uac00-\ud7a3\s]*[\uac00-\ud7a3]')
            for m in span_re.finditer(prompt):
                korean_texts.append({
                    "text": m.group(0).strip(),
                    "position": "auto",
                    "size": "auto",
                })

    scene = KOREAN_QUOTE_RE.sub("", prompt)
    scene = KOREAN_CHAR_RE.sub("", scene)
    for w in TEXT_REMOVAL_WORDS:
        scene = re.sub(rf"\b{re.escape(w)}\b", "", scene, flags=re.IGNORECASE)
    scene = re.sub(r"\s+", " ", scene).strip(" ,.")
    if not scene:
        scene = "cinematic photograph, detailed, high quality"
    return korean_texts, scene


def _load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    """Load TrueType font with fallbacks."""
    try:
        return ImageFont.truetype(font_path, size=size)
    except (OSError, IOError):
        # Common system fallbacks for Korean fonts
        for candidate in [
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        ]:
            try:
                return ImageFont.truetype(candidate, size=size)
            except (OSError, IOError):
                continue
        return ImageFont.load_default()


def _analyze_region_brightness(img: Image.Image, bbox: Tuple[int, int, int, int]) -> float:
    """Mean brightness of a region (0-255)."""
    region = np.array(img.crop(bbox).convert("L"))
    return float(region.mean())


def _analyze_region_complexity(img: Image.Image, bbox: Tuple[int, int, int, int]) -> float:
    """Standard deviation of a region — higher = more complex/textured."""
    region = np.array(img.crop(bbox).convert("L"))
    return float(region.std())


def _compute_text_layout(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> Tuple[List[str], int, int]:
    """Word-wrap Korean text and return (lines, total_width, total_height)."""
    lines = []
    current = ""
    for ch in text:
        test = current + ch
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)

    total_w = 0
    total_h = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        total_w = max(total_w, bbox[2] - bbox[0])
        total_h += (bbox[3] - bbox[1]) + 8
    return lines, total_w, total_h


def render_text_with_mask(
    base_img: Image.Image,
    texts: List[Dict],
    font_path: str,
    mask_dilate: int = 12,
    default_size_ratio: float = 0.08,
) -> Tuple[Image.Image, Image.Image]:
    """Render Korean texts onto base image and produce edge-only inpaint mask.

    Args:
        base_img: Background image from Z-Image.
        texts: List of {"text": str, "position": "auto"|"top"|"center"|"bottom"}
        font_path: Path to Korean TrueType font.
        mask_dilate: Mask dilation radius in pixels (edge-only region).

    Returns:
        (composited_image, border_mask)
    """
    W, H = base_img.size
    composited = base_img.convert("RGBA").copy()
    text_mask = Image.new("L", (W, H), 0)

    n_texts = len(texts)
    for idx, entry in enumerate(texts):
        text = entry["text"]
        position = entry.get("position", "auto")

        # Auto-size based on image dimensions
        size = entry.get("size", "auto")
        if size == "auto":
            font_size = max(32, int(min(W, H) * default_size_ratio))
        else:
            font_size = int(size)

        font = _load_font(font_path, font_size)

        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer)

        max_width = int(W * 0.85)
        lines, tw, th = _compute_text_layout(layer_draw, text, font, max_width)

        # Auto position: first text at top, last at bottom, middle at center
        if position == "auto":
            if n_texts == 1:
                position = "center"
            elif idx == 0:
                position = "top"
            elif idx == n_texts - 1:
                position = "bottom"
            else:
                position = "center"

        x = (W - tw) // 2
        if position == "top":
            y = int(H * 0.08)
        elif position == "bottom":
            y = int(H * 0.92) - th
        else:
            y = (H - th) // 2

        bbox = (max(0, x - 20), max(0, y - 10), min(W, x + tw + 20), min(H, y + th + 10))

        # Decide text color from background brightness
        brightness = _analyze_region_brightness(base_img, bbox)
        complexity = _analyze_region_complexity(base_img, bbox)

        if brightness < 128:
            main_color = (255, 255, 255)
            shadow_color = (0, 0, 0, 200)
            outline_color = (0, 0, 0, 255)
        else:
            main_color = (20, 20, 20)
            shadow_color = (255, 255, 255, 200)
            outline_color = (255, 255, 255, 255)

        # Add semi-transparent background panel if too complex
        if complexity > 45:
            pad = 18
            panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            panel_draw = ImageDraw.Draw(panel)
            bg_color = (0, 0, 0, 140) if brightness >= 128 else (255, 255, 255, 140)
            panel_draw.rounded_rectangle(
                [bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad],
                radius=16,
                fill=bg_color,
            )
            layer = Image.alpha_composite(layer, panel)
            layer_draw = ImageDraw.Draw(layer)

        # Draw each line: shadow → outline → main
        cy = y
        for line in lines:
            lbbox = layer_draw.textbbox((0, 0), line, font=font)
            lw = lbbox[2] - lbbox[0]
            lx = (W - lw) // 2

            # Shadow
            layer_draw.text((lx + 3, cy + 3), line, fill=shadow_color, font=font)
            # Outline (8-direction)
            for ox in (-2, -1, 0, 1, 2):
                for oy in (-2, -1, 0, 1, 2):
                    if ox == 0 and oy == 0:
                        continue
                    layer_draw.text((lx + ox, cy + oy), line, fill=outline_color, font=font)
            # Main
            layer_draw.text((lx, cy), line, fill=(*main_color, 255), font=font)

            cy += (lbbox[3] - lbbox[1]) + 8

        composited = Image.alpha_composite(composited, layer)

        # Build text mask from alpha channel of this layer's text only
        layer_alpha = np.array(layer.split()[-1])
        text_region_mask = (layer_alpha > 64).astype(np.uint8) * 255
        existing = np.array(text_mask)
        text_mask = Image.fromarray(np.maximum(existing, text_region_mask))

    # Edge-only mask: dilate - original
    text_arr = np.array(text_mask, dtype=np.int16)
    dilated = text_mask.filter(ImageFilter.MaxFilter(mask_dilate * 2 + 1))
    dilated_arr = np.array(dilated, dtype=np.int16)
    border = np.clip(dilated_arr - text_arr, 0, 255).astype(np.uint8)
    border_mask = Image.fromarray(border).filter(ImageFilter.GaussianBlur(radius=5))

    return composited.convert("RGB"), border_mask
