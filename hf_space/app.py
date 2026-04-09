# ──────────────────────────────────────────────────────────────────────
# LiteRT-LM  ·  Fairy-Tale AXIS Engine  ·  3D FlipBook PDF Viewer
# Integrated FastAPI application
# ──────────────────────────────────────────────────────────────────────

# ============================================================
# 1. Imports & Config
# ============================================================
import os, sys, json, re, uuid, time, sqlite3, base64, io, shutil
import asyncio, threading, traceback, tempfile, pathlib, logging
from datetime import datetime
from typing import Optional, List, Dict, Any

import requests
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# Optional imports (graceful fallback)
try:
    import fal_client
except ImportError:
    fal_client = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from reportlab.lib.pagesizes import mm
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False

try:
    from huggingface_hub import HfApi
    HF_HUB_OK = True
except ImportError:
    HF_HUB_OK = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("axis-engine")

# Environment
FIREWORKS_API_KEY = os.getenv("FIREWORKS_API") or os.getenv("FIREWORKS_API_KEY", "")
FAL_KEY = os.getenv("FAL_KEY", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")

FIREWORKS_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
LLM_MODEL = "accounts/fireworks/models/kimi-k2p5"
VLM_MODEL = "accounts/fireworks/models/qwen3-vl-235b-a22b-instruct"

BASE_DIR = pathlib.Path(__file__).parent
DATA_DIR = pathlib.Path("/tmp/axis_data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
PDF_DIR = DATA_DIR / "pdfs"
PDF_DIR.mkdir(exist_ok=True)
IMG_DIR = DATA_DIR / "images"
IMG_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "stories.db"

# ============================================================
# 2. Emergence Seed Loading
# ============================================================
EMERGENCE_SEED = {}
_seed_path = pathlib.Path(__file__).parent / "emergence_seed.json"
if _seed_path.exists():
    with open(_seed_path, "r", encoding="utf-8") as _f:
        EMERGENCE_SEED = json.load(_f)
    logger.info("Emergence seed loaded from %s", _seed_path)
else:
    logger.warning("emergence_seed.json not found at %s", _seed_path)

# ============================================================
# 3. SQLite DB Setup
# ============================================================
def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = _get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS stories (
        id TEXT PRIMARY KEY,
        title TEXT DEFAULT '',
        purpose TEXT DEFAULT '',
        style TEXT DEFAULT '',
        mood TEXT DEFAULT '',
        child_name TEXT DEFAULT '',
        child_age INTEGER DEFAULT 7,
        child_traits TEXT DEFAULT '',
        skeleton_json TEXT DEFAULT '{}',
        status TEXT DEFAULT 'pending',
        pdf_path TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        story_id TEXT NOT NULL,
        page_num INTEGER NOT NULL,
        text_ko TEXT DEFAULT '',
        image_prompt TEXT DEFAULT '',
        image_url TEXT DEFAULT '',
        image_path TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        FOREIGN KEY (story_id) REFERENCES stories(id)
    );
    CREATE TABLE IF NOT EXISTS verifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        story_id TEXT NOT NULL,
        page_num INTEGER DEFAULT 0,
        score REAL DEFAULT 0.0,
        feedback TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (story_id) REFERENCES stories(id)
    );
    """)
    conn.commit()
    conn.close()

init_db()

# ============================================================
# 4. Styles / Moods / Beat Sheet definitions
# ============================================================
STYLE_OPTIONS = [
    "수채화 동화",
    "파스텔 일러스트",
    "만화 스타일",
    "유화풍",
    "연필 스케치",
    "팝아트",
    "동양화",
]

MOOD_OPTIONS = [
    "따뜻하고 포근한",
    "신비롭고 몽환적인",
    "밝고 유쾌한",
    "모험적이고 용감한",
    "잔잔하고 서정적인",
]

BEAT_SHEET: Dict[int, str] = {
    1:  "평범한 일상 속 미세한 균열",
    2:  "부름/발견 - 호기심의 씨앗",
    3:  "문턱 넘기 - 새로운 세계 진입",
    4:  "첫 번째 시련과 조력자 등장",
    5:  "새로운 규칙 학습/탐험",
    6:  "동맹 형성과 중간 목표 달성",
    7:  "반전/배신/예상 밖의 장애물",
    8:  "가장 큰 두려움과 직면",
    9:  "모든 것을 잃는 순간",
    10: "내면의 발견/깨달음",
    11: "최종 결전/도전",
    12: "클라이맥스 - 성장의 증명",
    13: "새로운 균형/귀환",
    14: "변화된 일상",
    15: "여운과 열린 결말",
}

# ============================================================
# 5. LLM Utilities
# ============================================================
def llm_chat(messages: list, temperature: float = 0.82, max_tokens: int = 4096) -> str:
    """Call Fireworks Kimi-K2.5 LLM."""
    headers = {
        "Authorization": f"Bearer {FIREWORKS_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        resp = requests.post(FIREWORKS_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return ""


def vlm_analyze(image_url: str, prompt: str, max_tokens: int = 1024) -> str:
    """Call Fireworks Qwen3-VL for image analysis."""
    headers = {
        "Authorization": f"Bearer {FIREWORKS_API_KEY}",
        "Content-Type": "application/json",
    }
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    payload = {
        "model": VLM_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    try:
        resp = requests.post(FIREWORKS_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error("VLM call failed: %s", e)
        return ""


def generate_image_fal(prompt: str) -> str:
    """Generate image using FAL Grok Imagine and return URL."""
    if not FAL_KEY or fal_client is None:
        logger.warning("FAL_KEY not set or fal_client not installed, skipping image generation")
        return ""
    os.environ["FAL_KEY"] = FAL_KEY
    try:
        handler = fal_client.submit(
            "xai/grok-imagine-image",
            arguments={"prompt": prompt},
        )
        result = fal_client.result("xai/grok-imagine-image", handler.request_id)
        if result and "images" in result and len(result["images"]) > 0:
            return result["images"][0]["url"]
        return ""
    except Exception as e:
        logger.error("FAL image generation failed: %s", e)
        return ""

# ============================================================
# 6. Emergence Prompt Builder
# ============================================================
def build_emergence_system_prompt() -> str:
    """Build a rich system prompt from the emergence seed for story generation."""
    seed = EMERGENCE_SEED.get("hyper_divergent_emergence_seed", {})
    kernel = seed.get("system_kernel", {})
    dna = seed.get("narrative_dna_circuits", {})
    operators = seed.get("emergence_operators", {})
    img_directives = seed.get("image_prompt_directives", {})

    identity = dna.get("identity_matrix", {}).get("elements", {})
    linguistic = identity.get("linguistic_style", {})
    moral = identity.get("moral_alignment", {})
    fear = identity.get("subconscious_fear", {})
    capabilities = identity.get("latent_capabilities", {})
    char_depth = dna.get("character_depth_requirements", {})
    dialogue_sys = dna.get("dialogue_system", {})
    world = dna.get("world_building_scaffold", {})

    holographic = operators.get("holographic_interference", {})
    adversarial = operators.get("adversarial_dialectic", {})
    sensory = operators.get("sensory_immersion_engine", {})
    emotional = operators.get("emotional_architecture", {})
    read_aloud = operators.get("read_aloud_optimization", {})

    forbidden_starters = ", ".join(linguistic.get("forbidden_sentence_starters", []))
    forbidden_cliches = ", ".join(linguistic.get("forbidden_cliche_expressions", []))
    forbidden_moral = "; ".join(moral.get("forbidden_moral_delivery", []))
    permitted_moral = "; ".join(moral.get("permitted_moral_delivery", []))
    permitted_fears = "; ".join(fear.get("permitted_fears", []))
    comfort_palette = "; ".join(fear.get("comfort_sensory_palette", []))
    cliche_blacklist_items = ", ".join(adversarial.get("cliche_blacklist", [])[:10])

    protagonist_rules = "; ".join(char_depth.get("protagonist", {}).get("behavioral_consistency_rules", []))
    dialogue_rules = "; ".join(dialogue_sys.get("rules", []))

    system_prompt = f"""당신은 AXIS Narrative Singularity 엔진입니다.
동화 전문 작가로서 다음 규칙을 절대적으로 따르십시오.

[시스템 설정]
- 서사 온도: {kernel.get('narrative_temperature', 0.82)}
- 일관성 중력: {kernel.get('coherence_gravity', 0.91)}
- 상상력 한계: {kernel.get('imagination_ceiling', 'unlimited_within_rules')}
- 목표 재독률: {kernel.get('target_reread_count', 100)}회
- 이중 독자 모드: 활성 (아이가 즐기고 부모가 감동)

[언어 스타일]
- 금지 문장 시작어: {forbidden_starters}
- 금지 클리셰 표현: {forbidden_cliches}
- 대체 전략: {linguistic.get('replacement_strategy', '')}
- 감각 밀도: 페이지당 최소 {linguistic.get('sensory_density_per_page', 2)}개
- 은유 신선도 임계값: {linguistic.get('metaphor_freshness_threshold', 0.85)}
- 문장 패턴 다양성: {linguistic.get('sentence_pattern_diversity_min', 0.7)} 이상

[도덕/교훈]
- 교훈 직접 전달 금지: {forbidden_moral}
- 허용된 교훈 전달: {permitted_moral}
- 보여주기(show) 강제, 말하기(tell) 금지

[두려움과 안전]
- 허용 두려움: {permitted_fears}
- 위안 감각 팔레트: {comfort_palette}
- 부정 감정 후 2페이지 이내 회복

[캐릭터]
- 주인공 행동 규칙: {protagonist_rules}
- 어른 구출 금지, 데우스 엑스 마키나 금지
- 적대자: 순수악 금지, 반드시 이유가 있어야 함
- 조력자: 단순 조수가 아닌 자체 동기 필요

[대화]
- {dialogue_rules}
- 시그니처 대사: P3에서 가볍게 -> P8에서 좌절과 함께 -> P12에서 결정적 순간에 새로운 의미

[복선]
- 최소 {holographic.get('minimum_foreshadowing_seeds', 3)}개, 최대 {holographic.get('maximum_foreshadowing_seeds', 5)}개
- 복선 설치: P1-P4, 회수: P10-P15
- 미묘함 수준: {holographic.get('subtlety_level', 0.8)}

[클리셰 억제]
- 클리셰 억제력: {adversarial.get('cliche_suppression_force', 0.9)}
- 금지 클리셰: {cliche_blacklist_items}...

[감각 몰입]
- 페이지당 최소 {sensory.get('minimum_senses_per_page', 2)}개 감각
- 공감각 권장

[감정 설계]
- 울음 포인트 목표: P10-P11 또는 P13
- 방법: 가장 어두운 순간의 예상치 못한 친절 또는 성장의 인식

[읽어주기 최적화]
- 최대 40자 문장 권장
- 긴장: 짧은 문장 연속 / 평화: 길고 부드러운 문장
- 페이지 끝에 다음 궁금증 hook

모든 출력은 한국어로 작성하십시오."""
    return system_prompt

# ============================================================
# 7. Fairy Tale Generation Pipeline (Steps 1-4)
# ============================================================

def step1_create_skeleton(
    purpose: str, style: str, mood: str,
    child_name: str, child_age: int, child_traits: str,
) -> dict:
    """Generate story skeleton: title, theme, characters, foreshadowing via 1 LLM call."""
    system_prompt = build_emergence_system_prompt()

    beat_sheet_str = "\n".join([f"P{k}: {v}" for k, v in BEAT_SHEET.items()])

    user_prompt = f"""다음 조건으로 15페이지 동화의 뼈대를 생성하세요.

[아이 정보]
- 이름: {child_name}
- 나이: {child_age}세
- 특성: {child_traits}

[창작 조건]
- 목적/주제: {purpose}
- 일러스트 스타일: {style}
- 분위기: {mood}

[비트 시트 (15페이지)]
{beat_sheet_str}

다음 JSON 형식으로만 응답하세요:
{{
  "title": "동화 제목",
  "theme": "핵심 주제 한 문장",
  "characters": {{
    "protagonist": {{
      "name": "이름",
      "description": "외모/성격 설명",
      "flaw": "성장할 결점",
      "visual_anchors": "일관된 시각적 특징 (머리색, 의상 등)"
    }},
    "ally": {{
      "name": "이름",
      "description": "설명",
      "motivation": "자체 동기",
      "visual_anchors": "시각적 특징"
    }},
    "antagonist": {{
      "name": "이름/설명",
      "description": "설명",
      "reason": "적대 이유 (순수악 아닌)",
      "visual_anchors": "시각적 특징"
    }}
  }},
  "foreshadowing": [
    {{"seed_page": 1, "payoff_page": 11, "element": "설명"}},
    {{"seed_page": 2, "payoff_page": 12, "element": "설명"}},
    {{"seed_page": 3, "payoff_page": 13, "element": "설명"}}
  ],
  "signature_line": "반복될 핵심 대사",
  "world_rules": ["세계 규칙1", "세계 규칙2"],
  "magic_system": {{
    "type": "마법 체계 설명",
    "cost": "마법의 대가"
  }}
}}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    raw = llm_chat(messages, temperature=0.85, max_tokens=4096)

    # Extract JSON from response
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if json_match:
        try:
            skeleton = json.loads(json_match.group())
            return skeleton
        except json.JSONDecodeError:
            pass

    # Fallback skeleton
    return {
        "title": f"{child_name}의 모험",
        "theme": purpose,
        "characters": {
            "protagonist": {"name": child_name, "description": child_traits, "flaw": "두려움", "visual_anchors": "밝은 머리, 파란 외투"},
            "ally": {"name": "루미", "description": "빛나는 작은 생물", "motivation": "친구 찾기", "visual_anchors": "반짝이는 날개"},
            "antagonist": {"name": "그림자", "description": "어둠의 존재", "reason": "외로움", "visual_anchors": "어두운 안개"},
        },
        "foreshadowing": [
            {"seed_page": 1, "payoff_page": 11, "element": "주인공이 무심코 주운 조약돌"},
            {"seed_page": 2, "payoff_page": 12, "element": "조력자가 건넨 수수께끼 같은 말"},
            {"seed_page": 3, "payoff_page": 13, "element": "배경에 보이던 작은 빛"},
        ],
        "signature_line": "괜찮아, 한 걸음이면 돼.",
        "world_rules": ["빛은 용기에 반응한다", "그림자는 두려움을 먹는다"],
        "magic_system": {"type": "내면의 빛", "cost": "소중한 기억 하나"},
    }


def step2_generate_page_text(story_id: str, skeleton: dict) -> list:
    """Generate 15 pages of Korean text based on skeleton."""
    system_prompt = build_emergence_system_prompt()
    beat_sheet_str = "\n".join([f"P{k}: {v}" for k, v in BEAT_SHEET.items()])
    skeleton_str = json.dumps(skeleton, ensure_ascii=False, indent=2)

    emotional_map = EMERGENCE_SEED.get("hyper_divergent_emergence_seed", {}).get(
        "emergence_operators", {}
    ).get("emotional_architecture", {}).get("emotional_beat_map", {})
    emotional_str = "\n".join([
        f"P{k}: {v.get('primary', '')} / 독자: {v.get('reader_feels', '')}"
        for k, v in emotional_map.items()
    ]) if emotional_map else ""

    user_prompt = f"""다음 뼈대를 바탕으로 15페이지 동화 본문을 작성하세요.

[뼈대]
{skeleton_str}

[비트 시트]
{beat_sheet_str}

[감정 맵]
{emotional_str}

[규칙]
- 각 페이지는 120-180자 (읽어주기 최적)
- 페이지당 최소 2개 감각 묘사
- 금지 문장 시작어 절대 사용 금지
- 복선을 자연스럽게 심기
- 시그니처 대사를 P3, P8, P12에 변주하여 삽입
- 페이지 끝에 다음 페이지 호기심 유발 hook

다음 JSON 배열 형식으로만 응답하세요:
[
  {{"page": 1, "text": "본문..."}},
  {{"page": 2, "text": "본문..."}},
  ...
  {{"page": 15, "text": "본문..."}}
]"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    raw = llm_chat(messages, temperature=0.82, max_tokens=8192)

    # Extract JSON array
    json_match = re.search(r'\[[\s\S]*\]', raw)
    pages_data = []
    if json_match:
        try:
            pages_data = json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Ensure 15 pages
    if len(pages_data) < 15:
        for i in range(len(pages_data) + 1, 16):
            pages_data.append({"page": i, "text": f"(페이지 {i} 내용 생성 중...)"})

    # Save to DB
    conn = _get_db()
    for pd_item in pages_data[:15]:
        page_num = pd_item.get("page", 0)
        text = pd_item.get("text", "")
        conn.execute(
            "INSERT INTO pages (story_id, page_num, text_ko, status) VALUES (?, ?, ?, 'text_done')",
            (story_id, page_num, text),
        )
    conn.commit()
    conn.close()
    return pages_data[:15]


def step3_generate_page_image(
    story_id: str, page_num: int, text: str, style: str, characters: dict,
) -> str:
    """Generate an illustration for a single page via FAL + VLM verification."""
    # Build image prompt
    protagonist = characters.get("protagonist", {})
    visual_anchors = protagonist.get("visual_anchors", "")
    char_desc = protagonist.get("description", "")

    img_directives = EMERGENCE_SEED.get("hyper_divergent_emergence_seed", {}).get("image_prompt_directives", {})
    composition_rules = img_directives.get("composition_rules", [])
    consistency_anchors = img_directives.get("character_consistency_anchors", [])
    forbidden_visual = img_directives.get("forbidden_visual_elements", [])

    composition_hint = composition_rules[page_num % len(composition_rules)] if composition_rules else ""

    # Determine emotional tone from beat
    beat_desc = BEAT_SHEET.get(page_num, "")

    image_prompt = f"""Children's book illustration, {style} style.
Scene: {text[:200]}
Beat: {beat_desc}
Character: {char_desc}, {visual_anchors}
Composition: {composition_hint}
Consistency anchors: {', '.join(consistency_anchors[:2])}
Do NOT include: {', '.join(forbidden_visual[:2])}
High quality, detailed, child-friendly, warm lighting, storybook aesthetic."""

    # Save image prompt
    conn = _get_db()
    conn.execute(
        "UPDATE pages SET image_prompt = ? WHERE story_id = ? AND page_num = ?",
        (image_prompt, story_id, page_num),
    )
    conn.commit()
    conn.close()

    # Generate image
    image_url = generate_image_fal(image_prompt)

    if image_url:
        # VLM verification
        verification_prompt = f"""이 이미지는 동화 {page_num}페이지의 삽화입니다.
본문: {text[:150]}
캐릭터 시각적 특징: {visual_anchors}

다음을 확인하세요:
1. 텍스트 장면과 일치하는가? (1-10)
2. 캐릭터 일관성이 유지되는가? (1-10)
3. 아동 친화적인가? (1-10)
4. 전체 점수와 피드백

JSON으로 응답: {{"scene_match": N, "consistency": N, "child_safe": N, "total": N, "feedback": "..."}}"""

        vlm_result = vlm_analyze(image_url, verification_prompt)
        score = 7.0
        feedback = ""
        try:
            vr_match = re.search(r'\{[\s\S]*?\}', vlm_result)
            if vr_match:
                vr = json.loads(vr_match.group())
                score = float(vr.get("total", 7))
                feedback = vr.get("feedback", "")
        except Exception:
            pass

        # Save verification
        conn = _get_db()
        conn.execute(
            "INSERT INTO verifications (story_id, page_num, score, feedback) VALUES (?, ?, ?, ?)",
            (story_id, page_num, score, feedback),
        )

        # Download and save image
        img_filename = f"{story_id}_p{page_num:02d}.png"
        img_path = str(IMG_DIR / img_filename)
        try:
            img_resp = requests.get(image_url, timeout=60)
            if img_resp.status_code == 200:
                with open(img_path, "wb") as f:
                    f.write(img_resp.content)
        except Exception as e:
            logger.error("Image download failed for page %d: %s", page_num, e)
            img_path = ""

        conn.execute(
            "UPDATE pages SET image_url = ?, image_path = ?, status = 'image_done' WHERE story_id = ? AND page_num = ?",
            (image_url, img_path, story_id, page_num),
        )
        conn.commit()
        conn.close()
        return image_url

    conn = _get_db()
    conn.execute(
        "UPDATE pages SET status = 'image_failed' WHERE story_id = ? AND page_num = ?",
        (story_id, page_num),
    )
    conn.commit()
    conn.close()
    return ""


def step4_verify(story_id: str) -> dict:
    """MARL 5-agent quality verification."""
    conn = _get_db()
    story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
    pages = conn.execute(
        "SELECT * FROM pages WHERE story_id = ? ORDER BY page_num", (story_id,)
    ).fetchall()
    conn.close()

    if not story or not pages:
        return {"passed": False, "reason": "Story or pages not found"}

    skeleton = json.loads(story["skeleton_json"]) if story["skeleton_json"] else {}
    all_text = "\n\n".join([f"[P{p['page_num']}] {p['text_ko']}" for p in pages])

    agents = [
        {
            "name": "Plot_Logic_Agent",
            "instruction": "당신은 스토리 논리 검증 전문가입니다. 15페이지 동화의 플롯 논리를 검증하세요. 인과관계, 시간 흐름, 세계 규칙 일관성을 확인하세요.",
        },
        {
            "name": "Character_Voice_Agent",
            "instruction": "당신은 캐릭터 일관성 전문가입니다. 캐릭터의 목소리, 행동, 성장 아크가 일관적인지 검증하세요.",
        },
        {
            "name": "Emotional_Arc_Agent",
            "instruction": "당신은 감정 설계 전문가입니다. 비트 시트에 따른 감정 곡선이 적절한지, 카타르시스가 있는지 검증하세요.",
        },
        {
            "name": "Foreshadow_Agent",
            "instruction": "당신은 복선 검증 전문가입니다. 복선이 자연스럽게 설치되고 회수되는지 검증하세요.",
        },
        {
            "name": "Child_Safety_Agent",
            "instruction": "당신은 아동 안전 전문가입니다. 내용이 아동에게 적절한지, 금지된 두려움이 없는지, 교훈이 강요되지 않는지 검증하세요.",
        },
    ]

    results = []
    for agent in agents:
        messages = [
            {"role": "system", "content": agent["instruction"]},
            {"role": "user", "content": f"""[스토리 뼈대]
{json.dumps(skeleton, ensure_ascii=False, indent=2)[:1500]}

[전체 텍스트]
{all_text[:3000]}

10점 만점으로 평가하고 피드백을 주세요.
JSON 형식: {{"agent": "{agent['name']}", "score": N, "feedback": "..."}}"""},
        ]
        raw = llm_chat(messages, temperature=0.3, max_tokens=1024)
        try:
            match = re.search(r'\{[\s\S]*?\}', raw)
            if match:
                result = json.loads(match.group())
                results.append(result)
            else:
                results.append({"agent": agent["name"], "score": 7, "feedback": raw[:200]})
        except Exception:
            results.append({"agent": agent["name"], "score": 7, "feedback": raw[:200]})

    avg_score = sum(r.get("score", 0) for r in results) / max(len(results), 1)
    passed = avg_score >= 6.0

    # Save verifications
    conn = _get_db()
    for r in results:
        conn.execute(
            "INSERT INTO verifications (story_id, page_num, score, feedback) VALUES (?, ?, ?, ?)",
            (story_id, 0, r.get("score", 0), json.dumps(r, ensure_ascii=False)),
        )
    conn.commit()
    conn.close()

    return {
        "passed": passed,
        "average_score": round(avg_score, 2),
        "agents": results,
    }


def run_full_pipeline(params: dict):
    """Orchestrate complete story generation pipeline."""
    story_id = params["story_id"]
    conn = _get_db()
    conn.execute("UPDATE stories SET status = 'generating_skeleton' WHERE id = ?", (story_id,))
    conn.commit()
    conn.close()

    try:
        # Step 1: Skeleton
        skeleton = step1_create_skeleton(
            params["purpose"], params["style"], params["mood"],
            params["child_name"], params["child_age"], params["child_traits"],
        )
        title = skeleton.get("title", f"{params['child_name']}의 모험")

        conn = _get_db()
        conn.execute(
            "UPDATE stories SET title = ?, skeleton_json = ?, status = 'generating_text' WHERE id = ?",
            (title, json.dumps(skeleton, ensure_ascii=False), story_id),
        )
        conn.commit()
        conn.close()

        # Step 2: Page text
        pages_data = step2_generate_page_text(story_id, skeleton)

        conn = _get_db()
        conn.execute("UPDATE stories SET status = 'generating_images' WHERE id = ?", (story_id,))
        conn.commit()
        conn.close()

        # Step 3: Page images (sequential to avoid rate limits)
        characters = skeleton.get("characters", {})
        for pd_item in pages_data:
            page_num = pd_item.get("page", 0)
            text = pd_item.get("text", "")
            conn = _get_db()
            conn.execute(
                "UPDATE stories SET status = ? WHERE id = ?",
                (f"generating_image_p{page_num}", story_id),
            )
            conn.commit()
            conn.close()
            step3_generate_page_image(story_id, page_num, text, params["style"], characters)

        # Step 4: Verification
        conn = _get_db()
        conn.execute("UPDATE stories SET status = 'verifying' WHERE id = ?", (story_id,))
        conn.commit()
        conn.close()

        verification = step4_verify(story_id)

        # Step 5: Generate PDF
        conn = _get_db()
        conn.execute("UPDATE stories SET status = 'generating_pdf' WHERE id = ?", (story_id,))
        conn.commit()
        conn.close()

        pdf_path = generate_story_pdf(story_id)

        # Done
        conn = _get_db()
        final_status = "complete" if verification.get("passed", False) else "complete_with_warnings"
        conn.execute(
            "UPDATE stories SET status = ?, pdf_path = ? WHERE id = ?",
            (final_status, pdf_path, story_id),
        )
        conn.commit()
        conn.close()

        logger.info("Pipeline complete for story %s: %s", story_id, final_status)

    except Exception as e:
        logger.error("Pipeline failed for story %s: %s", story_id, traceback.format_exc())
        conn = _get_db()
        conn.execute(
            "UPDATE stories SET status = ? WHERE id = ?",
            (f"error: {str(e)[:200]}", story_id),
        )
        conn.commit()
        conn.close()

# ============================================================
# 8. PDF Generation (ReportLab)
# ============================================================
def generate_story_pdf(story_id: str) -> str:
    """Generate a 210x210mm square PDF from story pages."""
    if not REPORTLAB_OK:
        logger.warning("ReportLab not available, skipping PDF generation")
        return ""

    conn = _get_db()
    story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
    pages = conn.execute(
        "SELECT * FROM pages WHERE story_id = ? ORDER BY page_num", (story_id,)
    ).fetchall()
    conn.close()

    if not story or not pages:
        return ""

    pdf_filename = f"{story_id}.pdf"
    pdf_path = str(PDF_DIR / pdf_filename)

    page_w = 210 * mm
    page_h = 210 * mm

    c = rl_canvas.Canvas(pdf_path, pagesize=(page_w, page_h))

    # Try to register a Korean font
    font_name = "Helvetica"
    korean_font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/AppleGothic.ttf",
    ]
    for fpath in korean_font_paths:
        if os.path.exists(fpath):
            try:
                pdfmetrics.registerFont(TTFont("KoreanFont", fpath))
                font_name = "KoreanFont"
                break
            except Exception:
                continue

    title = story.get("title", "동화") if isinstance(story, dict) else (story["title"] if story["title"] else "동화")

    # Title page
    c.setFont(font_name, 28)
    c.drawCentredString(page_w / 2, page_h * 0.55, title)
    c.setFont(font_name, 14)
    child_name = story["child_name"] if story["child_name"] else ""
    if child_name:
        c.drawCentredString(page_w / 2, page_h * 0.42, f"{child_name}를 위한 이야기")
    c.showPage()

    # Content pages
    for page_row in pages:
        page_num = page_row["page_num"]
        text = page_row["text_ko"] or ""
        img_path = page_row["image_path"] or ""

        # Draw image (top portion)
        img_area_h = page_h * 0.62
        if img_path and os.path.exists(img_path):
            try:
                img = ImageReader(img_path)
                iw, ih = img.getSize()
                aspect = iw / ih
                draw_w = page_w - 20 * mm
                draw_h = draw_w / aspect
                if draw_h > img_area_h:
                    draw_h = img_area_h
                    draw_w = draw_h * aspect
                x = (page_w - draw_w) / 2
                y = page_h - 10 * mm - draw_h
                c.drawImage(img, x, y, draw_w, draw_h, preserveAspectRatio=True, mask='auto')
            except Exception as e:
                logger.error("PDF image draw error p%d: %s", page_num, e)

        # Draw text (bottom portion)
        text_y = page_h * 0.32
        c.setFont(font_name, 11)
        # Simple word wrap
        max_chars = 28
        lines = []
        for paragraph in text.split("\n"):
            while len(paragraph) > max_chars:
                lines.append(paragraph[:max_chars])
                paragraph = paragraph[max_chars:]
            lines.append(paragraph)

        for i, line in enumerate(lines[:8]):
            c.drawCentredString(page_w / 2, text_y - i * 16, line)

        # Page number
        c.setFont(font_name, 9)
        c.drawCentredString(page_w / 2, 8 * mm, f"- {page_num} -")
        c.showPage()

    c.save()
    logger.info("PDF generated: %s", pdf_path)
    return pdf_path


# ============================================================
# 9. PDF to Page Images (PyMuPDF)
# ============================================================
def pdf_to_base64_images(pdf_path: str, dpi: int = 150) -> list:
    """Convert each page of a PDF to a base64-encoded PNG image."""
    if fitz is None:
        return []
    if not os.path.exists(pdf_path):
        return []
    images = []
    try:
        doc = fitz.open(pdf_path)
        for page_idx in range(len(doc)):
            page = doc.load_page(page_idx)
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            images.append(b64)
        doc.close()
    except Exception as e:
        logger.error("PDF to images failed: %s", e)
    return images


def pdf_to_image_urls(pdf_path: str, story_id: str = "") -> list:
    """Convert PDF pages to saved PNG files and return relative URLs."""
    if fitz is None:
        return []
    if not os.path.exists(pdf_path):
        return []
    urls = []
    prefix = story_id or "pdf"
    try:
        doc = fitz.open(pdf_path)
        for page_idx in range(len(doc)):
            page = doc.load_page(page_idx)
            mat = fitz.Matrix(200 / 72, 200 / 72)
            pix = page.get_pixmap(matrix=mat)
            img_filename = f"{prefix}_page_{page_idx:03d}.png"
            img_path = str(IMG_DIR / img_filename)
            pix.save(img_path)
            urls.append(f"/api/image/{img_filename}")
        doc.close()
    except Exception as e:
        logger.error("PDF to image URLs failed: %s", e)
    return urls


# ============================================================
# 10. HF Dataset Upload/Download
# ============================================================
def upload_to_hf_dataset(story_id: str, repo_id: str = "Heartsync/fairy-tales") -> bool:
    """Upload story assets to HuggingFace dataset."""
    if not HF_HUB_OK or not HF_TOKEN:
        logger.warning("HF Hub not available or HF_TOKEN not set")
        return False
    try:
        api = HfApi(token=HF_TOKEN)
        conn = _get_db()
        story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
        pages = conn.execute(
            "SELECT * FROM pages WHERE story_id = ? ORDER BY page_num", (story_id,)
        ).fetchall()
        conn.close()

        if not story:
            return False

        # Upload PDF
        pdf_path = story["pdf_path"]
        if pdf_path and os.path.exists(pdf_path):
            api.upload_file(
                path_or_fileobj=pdf_path,
                path_in_repo=f"stories/{story_id}/{story_id}.pdf",
                repo_id=repo_id,
                repo_type="dataset",
            )

        # Upload images
        for p in pages:
            if p["image_path"] and os.path.exists(p["image_path"]):
                fname = os.path.basename(p["image_path"])
                api.upload_file(
                    path_or_fileobj=p["image_path"],
                    path_in_repo=f"stories/{story_id}/images/{fname}",
                    repo_id=repo_id,
                    repo_type="dataset",
                )

        # Upload metadata
        meta = {
            "id": story["id"],
            "title": story["title"],
            "purpose": story["purpose"],
            "style": story["style"],
            "mood": story["mood"],
            "child_name": story["child_name"],
            "child_age": story["child_age"],
            "skeleton": json.loads(story["skeleton_json"]) if story["skeleton_json"] else {},
            "pages": [{"page_num": p["page_num"], "text": p["text_ko"]} for p in pages],
            "created_at": story["created_at"],
        }
        meta_bytes = json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")
        api.upload_file(
            path_or_fileobj=io.BytesIO(meta_bytes),
            path_in_repo=f"stories/{story_id}/metadata.json",
            repo_id=repo_id,
            repo_type="dataset",
        )
        logger.info("Uploaded story %s to HF dataset %s", story_id, repo_id)
        return True
    except Exception as e:
        logger.error("HF upload failed: %s", e)
        return False


def download_from_hf_dataset(story_id: str, repo_id: str = "Heartsync/fairy-tales") -> bool:
    """Download story assets from HuggingFace dataset."""
    if not HF_HUB_OK or not HF_TOKEN:
        return False
    try:
        api = HfApi(token=HF_TOKEN)
        # Download metadata
        meta_path = api.hf_hub_download(
            repo_id=repo_id,
            filename=f"stories/{story_id}/metadata.json",
            repo_type="dataset",
            token=HF_TOKEN,
        )
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        logger.info("Downloaded story %s metadata from HF", story_id)
        return True
    except Exception as e:
        logger.error("HF download failed: %s", e)
        return False

# ============================================================
# 11. Existing PDF Caching System
# ============================================================
PDF_CACHE: Dict[str, list] = {}
PDF_ANALYSIS_CACHE: Dict[str, dict] = {}

BUILT_IN_PDFS = {
    "prompt": {
        "label": "Prompt Engineering",
        "url": "https://huggingface.co/spaces/Heartsync/3d-kid/resolve/main/prompt.pdf",
        "local_app_dir": str(BASE_DIR / "prompt.pdf"),
        "local": str(PDF_DIR / "prompt.pdf"),
    },
    "ktx2512": {
        "label": "KTX 2512",
        "url": "https://huggingface.co/spaces/Heartsync/3d-kid/resolve/main/ktx2512.pdf",
        "local_app_dir": str(BASE_DIR / "ktx2512.pdf"),
        "local": str(PDF_DIR / "ktx2512.pdf"),
    },
}


def ensure_pdf_downloaded(key: str) -> str:
    """Download a built-in PDF if not already cached locally. Check app dir first."""
    info = BUILT_IN_PDFS.get(key)
    if not info:
        return ""
    # Check if PDF exists in app directory (same dir as app.py)
    app_dir_path = info.get("local_app_dir", "")
    if app_dir_path and os.path.exists(app_dir_path):
        return app_dir_path
    local_path = info["local"]
    if os.path.exists(local_path):
        return local_path
    # Download with auth header for private spaces
    try:
        headers = {}
        if HF_TOKEN:
            headers["Authorization"] = f"Bearer {HF_TOKEN}"
        resp = requests.get(info["url"], headers=headers, timeout=120)
        resp.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(resp.content)
        logger.info("Downloaded built-in PDF: %s -> %s", key, local_path)
        return local_path
    except Exception as e:
        logger.error("Failed to download PDF %s: %s", key, e)
        return ""


def get_cached_pdf_pages(pdf_key: str) -> list:
    """Get base64 page images for a built-in PDF, using cache."""
    if pdf_key in PDF_CACHE:
        return PDF_CACHE[pdf_key]
    local_path = ensure_pdf_downloaded(pdf_key)
    if not local_path:
        return []
    pages = pdf_to_base64_images(local_path)
    PDF_CACHE[pdf_key] = pages
    return pages


# ============================================================
# 12. Existing VLM Analysis System
# ============================================================
def analyze_pdf_page_vlm(pdf_key: str, page_idx: int) -> str:
    """Analyze a single PDF page using VLM."""
    cache_key = f"{pdf_key}_{page_idx}"
    if cache_key in PDF_ANALYSIS_CACHE:
        return PDF_ANALYSIS_CACHE[cache_key]["analysis"]

    pages = get_cached_pdf_pages(pdf_key)
    if page_idx < 0 or page_idx >= len(pages):
        return "Page not found."

    b64_img = pages[page_idx]
    data_url = f"data:image/png;base64,{b64_img}"

    analysis = vlm_analyze(
        data_url,
        "이 PDF 페이지의 내용을 상세히 분석하고 요약해주세요. 텍스트, 이미지, 도표 등 모든 요소를 포함하세요.",
        max_tokens=2048,
    )

    PDF_ANALYSIS_CACHE[cache_key] = {
        "analysis": analysis,
        "page_idx": page_idx,
        "pdf_key": pdf_key,
    }
    return analysis


def chatbot_answer(pdf_key: str, question: str, page_idx: int = 0) -> str:
    """Answer a question about a PDF page using VLM analysis + LLM."""
    # First get the page analysis
    analysis = analyze_pdf_page_vlm(pdf_key, page_idx)

    messages = [
        {
            "role": "system",
            "content": "당신은 PDF 문서 분석 도우미입니다. 주어진 페이지 분석을 바탕으로 사용자 질문에 정확하고 도움이 되는 답변을 하세요. 한국어로 답변하세요.",
        },
        {
            "role": "user",
            "content": f"""[PDF 페이지 분석 결과]
{analysis}

[사용자 질문]
{question}

위 분석 내용을 바탕으로 질문에 답변해주세요.""",
        },
    ]

    return llm_chat(messages, temperature=0.4, max_tokens=2048)

# ============================================================
# 13. FastAPI Endpoints (existing + new)
# ============================================================
app = FastAPI(title="LiteRT-LM AXIS Engine", version="2.0")

# Serve static files (JS, CSS, MP3 in the same directory)
app.mount("/static", StaticFiles(directory=str(BASE_DIR)), name="static")

# ---------- Image serving ----------
@app.get("/api/image/{filename}")
async def serve_image(filename: str):
    """Serve generated images."""
    img_path = IMG_DIR / filename
    if not img_path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(str(img_path), media_type="image/png")

# ---------- Existing PDF endpoints ----------
@app.get("/api/pdf/list")
async def list_pdfs():
    """List available built-in PDFs."""
    result = []
    for key, info in BUILT_IN_PDFS.items():
        result.append({"key": key, "label": info["label"]})
    return JSONResponse(result)


@app.get("/api/pdf/{pdf_key}/pages")
async def get_pdf_pages(pdf_key: str):
    """Get base64 page images for a built-in PDF."""
    pages = get_cached_pdf_pages(pdf_key)
    if not pages:
        raise HTTPException(404, "PDF not found or could not be processed")
    return JSONResponse({"pdf_key": pdf_key, "total_pages": len(pages), "pages": pages})


@app.post("/api/pdf/{pdf_key}/analyze")
async def analyze_pdf_page(pdf_key: str, request: Request):
    """Analyze a specific PDF page with VLM."""
    body = await request.json()
    page_idx = body.get("page_idx", 0)
    analysis = analyze_pdf_page_vlm(pdf_key, page_idx)
    return JSONResponse({"pdf_key": pdf_key, "page_idx": page_idx, "analysis": analysis})


@app.post("/api/chat")
async def chat_endpoint(request: Request):
    """AI chatbot endpoint for PDF Q&A."""
    body = await request.json()
    pdf_key = body.get("pdf_key", "prompt")
    question = body.get("question", "")
    page_idx = body.get("page_idx", 0)
    if not question:
        raise HTTPException(400, "question is required")
    answer = chatbot_answer(pdf_key, question, page_idx)
    return JSONResponse({"answer": answer})


# ---------- New Story endpoints ----------
@app.post("/api/story/create")
async def create_story(request: Request, background_tasks: BackgroundTasks):
    """Start fairy tale generation pipeline."""
    body = await request.json()
    story_id = str(uuid.uuid4())[:8]

    purpose = body.get("purpose", "용기와 우정에 대한 이야기")
    style = body.get("style", "수채화 동화")
    mood = body.get("mood", "따뜻하고 포근한")
    child_name = body.get("child_name", "하늘")
    child_age = int(body.get("child_age", 7))
    child_traits = body.get("child_traits", "호기심 많고 상상력이 풍부한")

    conn = _get_db()
    conn.execute(
        """INSERT INTO stories (id, purpose, style, mood, child_name, child_age, child_traits, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'queued')""",
        (story_id, purpose, style, mood, child_name, child_age, child_traits),
    )
    conn.commit()
    conn.close()

    params = {
        "story_id": story_id,
        "purpose": purpose,
        "style": style,
        "mood": mood,
        "child_name": child_name,
        "child_age": child_age,
        "child_traits": child_traits,
    }

    # Run pipeline in background thread
    thread = threading.Thread(target=run_full_pipeline, args=(params,), daemon=True)
    thread.start()

    return JSONResponse({"story_id": story_id, "status": "queued"})


@app.get("/api/story/status/{story_id}")
async def get_story_status(story_id: str):
    """Poll generation progress."""
    conn = _get_db()
    story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
    if not story:
        conn.close()
        raise HTTPException(404, "Story not found")

    pages = conn.execute(
        "SELECT page_num, status FROM pages WHERE story_id = ? ORDER BY page_num",
        (story_id,),
    ).fetchall()
    conn.close()

    pages_status = [{"page_num": p["page_num"], "status": p["status"]} for p in pages]
    total_pages = len(pages_status)
    done_pages = sum(1 for p in pages_status if p["status"] in ("image_done", "text_done"))

    return JSONResponse({
        "story_id": story_id,
        "title": story["title"] or "",
        "status": story["status"],
        "progress": {
            "total_pages": total_pages,
            "done_pages": done_pages,
            "percent": round(done_pages / max(total_pages, 1) * 100, 1),
        },
        "pages": pages_status,
    })


@app.get("/api/story/list")
async def list_stories():
    """List generated stories for card gallery."""
    conn = _get_db()
    stories = conn.execute(
        "SELECT id, title, style, mood, child_name, child_age, status, pdf_path, created_at FROM stories ORDER BY created_at DESC LIMIT 50"
    ).fetchall()

    result = []
    for s in stories:
        # Get thumbnail (first page image)
        first_page = conn.execute(
            "SELECT image_url, image_path FROM pages WHERE story_id = ? AND page_num = 1",
            (s["id"],),
        ).fetchone()
        thumbnail = ""
        if first_page:
            if first_page["image_path"] and os.path.exists(first_page["image_path"]):
                thumbnail = f"/api/image/{os.path.basename(first_page['image_path'])}"
            elif first_page["image_url"]:
                thumbnail = first_page["image_url"]

        result.append({
            "id": s["id"],
            "title": s["title"] or "생성 중...",
            "style": s["style"],
            "mood": s["mood"],
            "child_name": s["child_name"],
            "child_age": s["child_age"],
            "status": s["status"],
            "has_pdf": bool(s["pdf_path"] and os.path.exists(s["pdf_path"] if s["pdf_path"] else "")),
            "thumbnail": thumbnail,
            "created_at": s["created_at"],
        })
    conn.close()
    return JSONResponse(result)


@app.get("/api/story/{story_id}/flipbook")
async def get_story_flipbook(story_id: str):
    """Get FlipBook page images JSON for a generated story."""
    conn = _get_db()
    story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
    if not story:
        conn.close()
        raise HTTPException(404, "Story not found")

    pdf_path = story["pdf_path"]
    conn.close()

    if pdf_path and os.path.exists(pdf_path):
        pages_b64 = pdf_to_base64_images(pdf_path)
        return JSONResponse({
            "story_id": story_id,
            "title": story["title"],
            "total_pages": len(pages_b64),
            "pages": pages_b64,
        })

    # Fallback: return individual page images
    conn = _get_db()
    pages = conn.execute(
        "SELECT page_num, image_path, image_url, text_ko FROM pages WHERE story_id = ? ORDER BY page_num",
        (story_id,),
    ).fetchall()
    conn.close()

    page_images = []
    for p in pages:
        if p["image_path"] and os.path.exists(p["image_path"]):
            with open(p["image_path"], "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
                page_images.append(b64)
        else:
            page_images.append("")

    return JSONResponse({
        "story_id": story_id,
        "title": story["title"],
        "total_pages": len(page_images),
        "pages": page_images,
    })


@app.get("/api/story/{story_id}/pdf")
async def download_story_pdf(story_id: str):
    """Download the generated PDF file."""
    conn = _get_db()
    story = conn.execute("SELECT pdf_path, title FROM stories WHERE id = ?", (story_id,)).fetchone()
    conn.close()

    if not story or not story["pdf_path"] or not os.path.exists(story["pdf_path"]):
        raise HTTPException(404, "PDF not found")

    filename = f"{story['title'] or story_id}.pdf"
    return FileResponse(
        story["pdf_path"],
        media_type="application/pdf",
        filename=filename,
    )

# ============================================================
# 14. Inline HTML (Comic Style UI)
# ============================================================
MAIN_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>AXIS Fairy Tale Engine + 3D FlipBook</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Bangers&family=Comic+Neue:wght@400;700&display=swap" rel="stylesheet"/>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<style>
/* ===== RESET & BASE ===== */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Comic Neue', 'Segoe UI', sans-serif;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    color: #f0f0f0;
    overflow-x: hidden;
    min-height: 100vh;
}
h1, h2, h3, h4, h5 { font-family: 'Bangers', 'Comic Neue', cursive; letter-spacing: 1px; }

/* ===== COMIC STYLE VARIABLES ===== */
:root {
    --yellow: #FACC15;
    --blue: #3B82F6;
    --purple: #8B5CF6;
    --red: #EF4444;
    --dark: #1F2937;
    --border-w: 3px;
    --shadow: 3px 3px 0 #1F2937;
    --radius: 10px;
}

/* ===== TOP HEADER ===== */
.top-header {
    background: linear-gradient(90deg, var(--purple), var(--blue));
    border-bottom: 4px solid var(--dark);
    padding: 12px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    z-index: 100;
    position: relative;
}
.top-header h1 {
    font-size: 1.6rem;
    color: var(--yellow);
    text-shadow: 2px 2px 0 var(--dark);
}
.top-header .subtitle {
    font-size: 0.85rem;
    color: rgba(255,255,255,0.8);
    font-family: 'Comic Neue', sans-serif;
}

/* ===== MAIN LAYOUT ===== */
.main-container {
    display: flex;
    height: calc(100vh - 60px);
    position: relative;
}

/* ===== FLIPBOOK VIEWER ===== */
#viewer {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    overflow: hidden;
    background: radial-gradient(ellipse at center, #1a1a3e 0%, #0d0d2b 100%);
}
#viewer canvas { max-width: 100%; max-height: 100%; }
.viewer-controls {
    position: absolute;
    bottom: 20px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    gap: 12px;
    z-index: 10;
}
.viewer-controls button {
    background: var(--blue);
    color: white;
    border: var(--border-w) solid var(--dark);
    border-radius: var(--radius);
    padding: 10px 20px;
    font-family: 'Bangers', cursive;
    font-size: 1rem;
    cursor: pointer;
    box-shadow: var(--shadow);
    transition: transform 0.1s, box-shadow 0.1s;
}
.viewer-controls button:hover {
    transform: translate(-1px, -1px);
    box-shadow: 4px 4px 0 var(--dark);
}
.viewer-controls button:active {
    transform: translate(1px, 1px);
    box-shadow: 1px 1px 0 var(--dark);
}
.page-indicator {
    position: absolute;
    bottom: 70px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(0,0,0,0.7);
    color: var(--yellow);
    padding: 6px 16px;
    border-radius: 20px;
    font-family: 'Bangers', cursive;
    font-size: 0.95rem;
    z-index: 10;
}
#loading-overlay {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(15,15,40,0.9);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    z-index: 50;
}
#loading-overlay .spinner {
    width: 50px; height: 50px;
    border: 4px solid rgba(255,255,255,0.2);
    border-top: 4px solid var(--yellow);
    border-radius: 50%;
    animation: spin 1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
#loading-overlay p {
    margin-top: 16px;
    color: var(--yellow);
    font-family: 'Bangers', cursive;
    font-size: 1.2rem;
}

/* ===== FLOATING BUTTONS ===== */
.float-btn {
    position: fixed;
    width: 56px; height: 56px;
    border-radius: 50%;
    border: 3px solid var(--dark);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 1.5rem;
    z-index: 200;
    box-shadow: var(--shadow);
    transition: transform 0.2s;
}
.float-btn:hover { transform: scale(1.1); }

/* Story creation button (left) */
#btn-story-create {
    bottom: 24px;
    left: 24px;
    background: linear-gradient(135deg, var(--purple), var(--blue));
    color: var(--yellow);
}

/* Chat button (right) */
#btn-chat {
    bottom: 24px;
    right: 24px;
    background: linear-gradient(135deg, var(--blue), var(--purple));
    color: white;
}

/* PDF switch buttons */
.pdf-switch-btns {
    position: fixed;
    top: 80px;
    right: 24px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    z-index: 200;
}
.pdf-switch-btns button {
    background: var(--dark);
    color: var(--yellow);
    border: 2px solid var(--yellow);
    border-radius: 8px;
    padding: 8px 14px;
    font-family: 'Comic Neue', sans-serif;
    font-size: 0.8rem;
    font-weight: 700;
    cursor: pointer;
    box-shadow: var(--shadow);
    transition: background 0.2s;
}
.pdf-switch-btns button:hover { background: var(--purple); }
.pdf-switch-btns button.active { background: var(--blue); border-color: white; }

/* Gallery button */
#btn-gallery {
    bottom: 90px;
    left: 24px;
    background: linear-gradient(135deg, var(--yellow), #f59e0b);
    color: var(--dark);
    font-size: 1.3rem;
}

/* ===== SLIDE PANELS ===== */
.slide-panel {
    position: fixed;
    top: 0;
    height: 100vh;
    width: 400px;
    max-width: 90vw;
    background: linear-gradient(180deg, #1e1e3f 0%, #151530 100%);
    border: 3px solid var(--dark);
    z-index: 300;
    transition: transform 0.35s cubic-bezier(0.4,0,0.2,1);
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.slide-panel.left { left: 0; transform: translateX(-110%); border-right: 4px solid var(--purple); }
.slide-panel.left.open { transform: translateX(0); }
.slide-panel.right { right: 0; transform: translateX(110%); border-left: 4px solid var(--blue); }
.slide-panel.right.open { transform: translateX(0); }

.panel-header {
    padding: 16px 20px;
    background: linear-gradient(90deg, var(--purple), var(--blue));
    border-bottom: 3px solid var(--dark);
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.panel-header h2 {
    font-size: 1.3rem;
    color: var(--yellow);
    text-shadow: 1px 1px 0 var(--dark);
}
.panel-close {
    background: var(--red);
    color: white;
    border: 2px solid var(--dark);
    border-radius: 50%;
    width: 32px; height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-weight: bold;
    font-size: 1rem;
    box-shadow: 2px 2px 0 var(--dark);
}
.panel-body { flex: 1; overflow-y: auto; padding: 20px; }

/* ===== STORY CREATION FORM ===== */
.form-group {
    margin-bottom: 16px;
}
.form-group label {
    display: block;
    font-family: 'Bangers', cursive;
    font-size: 0.95rem;
    color: var(--yellow);
    margin-bottom: 6px;
    letter-spacing: 0.5px;
}
.form-group input,
.form-group textarea,
.form-group select {
    width: 100%;
    padding: 10px 14px;
    background: rgba(255,255,255,0.08);
    border: 2px solid rgba(255,255,255,0.15);
    border-radius: 8px;
    color: #f0f0f0;
    font-family: 'Comic Neue', sans-serif;
    font-size: 0.95rem;
    outline: none;
    transition: border-color 0.2s;
}
.form-group input:focus,
.form-group textarea:focus,
.form-group select:focus {
    border-color: var(--purple);
}
.form-group textarea { resize: vertical; min-height: 70px; }
.form-group select option { background: #1e1e3f; color: #f0f0f0; }

.btn-submit {
    width: 100%;
    padding: 14px;
    background: linear-gradient(90deg, var(--purple), var(--blue));
    color: white;
    border: 3px solid var(--dark);
    border-radius: var(--radius);
    font-family: 'Bangers', cursive;
    font-size: 1.2rem;
    cursor: pointer;
    box-shadow: var(--shadow);
    transition: transform 0.1s;
    letter-spacing: 1px;
}
.btn-submit:hover { transform: translate(-1px, -1px); box-shadow: 4px 4px 0 var(--dark); }
.btn-submit:active { transform: translate(1px, 1px); box-shadow: 1px 1px 0 var(--dark); }
.btn-submit:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

/* Progress display */
.progress-box {
    margin-top: 20px;
    padding: 16px;
    background: rgba(0,0,0,0.3);
    border: 2px solid var(--purple);
    border-radius: var(--radius);
    display: none;
}
.progress-box.visible { display: block; }
.progress-bar-outer {
    height: 12px;
    background: rgba(255,255,255,0.1);
    border-radius: 6px;
    overflow: hidden;
    margin: 10px 0;
}
.progress-bar-inner {
    height: 100%;
    background: linear-gradient(90deg, var(--purple), var(--blue), var(--yellow));
    border-radius: 6px;
    transition: width 0.5s ease;
    width: 0%;
}
.progress-status {
    font-size: 0.85rem;
    color: var(--yellow);
    font-family: 'Comic Neue', sans-serif;
}

/* ===== CHAT PANEL ===== */
.chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
}
.chat-msg {
    max-width: 85%;
    padding: 10px 14px;
    border-radius: 12px;
    font-size: 0.9rem;
    line-height: 1.5;
    border: 2px solid var(--dark);
}
.chat-msg.user {
    align-self: flex-end;
    background: var(--blue);
    color: white;
    border-bottom-right-radius: 4px;
}
.chat-msg.assistant {
    align-self: flex-start;
    background: rgba(139,92,246,0.3);
    color: #e0e0e0;
    border-bottom-left-radius: 4px;
}
.chat-input-area {
    padding: 12px 16px;
    border-top: 3px solid var(--dark);
    display: flex;
    gap: 8px;
}
.chat-input-area input {
    flex: 1;
    padding: 10px 14px;
    background: rgba(255,255,255,0.08);
    border: 2px solid rgba(255,255,255,0.15);
    border-radius: 8px;
    color: #f0f0f0;
    font-family: 'Comic Neue', sans-serif;
    font-size: 0.9rem;
    outline: none;
}
.chat-input-area input:focus { border-color: var(--blue); }
.chat-input-area button {
    padding: 10px 18px;
    background: var(--blue);
    color: white;
    border: 2px solid var(--dark);
    border-radius: 8px;
    font-family: 'Bangers', cursive;
    cursor: pointer;
    box-shadow: 2px 2px 0 var(--dark);
}

/* ===== GALLERY OVERLAY ===== */
#gallery-overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(10,10,30,0.95);
    z-index: 400;
    display: none;
    flex-direction: column;
    overflow: hidden;
}
#gallery-overlay.open { display: flex; }
.gallery-header {
    padding: 16px 24px;
    background: linear-gradient(90deg, var(--purple), var(--blue));
    border-bottom: 4px solid var(--dark);
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.gallery-header h2 {
    font-family: 'Bangers', cursive;
    font-size: 1.5rem;
    color: var(--yellow);
    text-shadow: 2px 2px 0 var(--dark);
}
.gallery-body {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 20px;
    align-content: start;
}

/* Story Cards */
.story-card {
    background: linear-gradient(145deg, #1e1e3f, #252550);
    border: 3px solid var(--dark);
    border-radius: 12px;
    overflow: hidden;
    box-shadow: var(--shadow);
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
}
.story-card:hover {
    transform: translateY(-4px);
    box-shadow: 5px 5px 0 var(--dark);
}
.story-card .card-thumb {
    width: 100%;
    height: 180px;
    background: linear-gradient(135deg, #2a2a5a, #1a1a3e);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
}
.story-card .card-thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}
.story-card .card-thumb .placeholder {
    font-size: 3rem;
    opacity: 0.3;
}
.story-card .card-body {
    padding: 14px;
}
.story-card .card-title {
    font-family: 'Bangers', cursive;
    font-size: 1.1rem;
    color: var(--yellow);
    margin-bottom: 6px;
}
.story-card .card-meta {
    font-size: 0.8rem;
    color: rgba(255,255,255,0.6);
    margin-bottom: 8px;
}
.story-card .card-status {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 700;
}
.card-status.complete { background: #22c55e; color: var(--dark); }
.card-status.generating { background: var(--yellow); color: var(--dark); }
.card-status.error { background: var(--red); color: white; }
.card-status.queued { background: var(--purple); color: white; }
.story-card .card-actions {
    display: flex;
    gap: 8px;
    margin-top: 10px;
}
.story-card .card-actions button {
    flex: 1;
    padding: 8px;
    border: 2px solid var(--dark);
    border-radius: 8px;
    font-family: 'Comic Neue', sans-serif;
    font-size: 0.8rem;
    font-weight: 700;
    cursor: pointer;
    box-shadow: 2px 2px 0 var(--dark);
}
.card-actions .btn-view { background: var(--blue); color: white; }
.card-actions .btn-download { background: var(--yellow); color: var(--dark); }

/* ===== RESPONSIVE ===== */
@media (max-width: 768px) {
    .slide-panel { width: 100vw; max-width: 100vw; }
    .gallery-body { grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
    .top-header h1 { font-size: 1.2rem; }
}
</style>
</head>
<body>

<!-- TOP HEADER -->
<div class="top-header">
    <div>
        <h1>AXIS Fairy Tale Engine</h1>
        <div class="subtitle">3D FlipBook PDF Viewer + AI Story Generator</div>
    </div>
    <div style="display:flex;gap:10px;align-items:center;">
        <span style="font-size:0.8rem;color:rgba(255,255,255,0.6);">Powered by Kimi-K2.5 + Grok Imagine</span>
    </div>
</div>

<!-- MAIN CONTAINER -->
<div class="main-container">
    <!-- FLIPBOOK VIEWER -->
    <div id="viewer">
        <div id="loading-overlay">
            <div class="spinner"></div>
            <p>Loading FlipBook...</p>
        </div>
        <canvas id="flipbook-canvas"></canvas>
        <div class="page-indicator" id="page-indicator">Page 1 / 1</div>
        <div class="viewer-controls">
            <button onclick="flipPrev()">&#9664; Prev</button>
            <button onclick="flipNext()">Next &#9654;</button>
        </div>
    </div>
</div>

<!-- FLOATING BUTTONS -->
<div class="float-btn" id="btn-story-create" onclick="toggleStoryPanel()" title="Create Fairy Tale">&#10024;</div>
<div class="float-btn" id="btn-gallery" onclick="toggleGallery()" title="Story Gallery">&#128218;</div>
<div class="float-btn" id="btn-chat" onclick="toggleChatPanel()" title="AI Chat">&#128172;</div>

<!-- PDF SWITCH BUTTONS -->
<div class="pdf-switch-btns" id="pdf-switch-btns"></div>

<!-- STORY CREATION PANEL (LEFT) -->
<div class="slide-panel left" id="story-panel">
    <div class="panel-header">
        <h2>&#10024; Create Fairy Tale</h2>
        <div class="panel-close" onclick="toggleStoryPanel()">&#10005;</div>
    </div>
    <div class="panel-body">
        <div class="form-group">
            <label>Purpose / Theme (목적/주제)</label>
            <textarea id="inp-purpose" placeholder="예: 용기와 우정에 대한 이야기, 어둠을 두려워하는 아이를 위한 이야기">용기와 우정에 대한 이야기</textarea>
        </div>
        <div class="form-group">
            <label>Illustration Style (스타일)</label>
            <select id="inp-style">
                <option value="수채화 동화">수채화 동화</option>
                <option value="파스텔 일러스트">파스텔 일러스트</option>
                <option value="만화 스타일">만화 스타일</option>
                <option value="유화풍">유화풍</option>
                <option value="연필 스케치">연필 스케치</option>
                <option value="팝아트">팝아트</option>
                <option value="동양화">동양화</option>
            </select>
        </div>
        <div class="form-group">
            <label>Mood (분위기)</label>
            <select id="inp-mood">
                <option value="따뜻하고 포근한">따뜻하고 포근한</option>
                <option value="신비롭고 몽환적인">신비롭고 몽환적인</option>
                <option value="밝고 유쾌한">밝고 유쾌한</option>
                <option value="모험적이고 용감한">모험적이고 용감한</option>
                <option value="잔잔하고 서정적인">잔잔하고 서정적인</option>
            </select>
        </div>
        <div class="form-group">
            <label>Child's Name (이름)</label>
            <input type="text" id="inp-child-name" placeholder="하늘" value="하늘"/>
        </div>
        <div class="form-group">
            <label>Child's Age (나이)</label>
            <input type="number" id="inp-child-age" min="3" max="12" value="7"/>
        </div>
        <div class="form-group">
            <label>Child's Traits (특성)</label>
            <textarea id="inp-child-traits" placeholder="예: 호기심 많고, 동물을 좋아하고, 가끔 겁이 많은">호기심 많고 상상력이 풍부한</textarea>
        </div>
        <button class="btn-submit" id="btn-generate" onclick="startGeneration()">&#9889; Generate Fairy Tale</button>

        <div class="progress-box" id="progress-box">
            <div class="progress-status" id="progress-status">Waiting...</div>
            <div class="progress-bar-outer">
                <div class="progress-bar-inner" id="progress-bar"></div>
            </div>
            <div id="progress-detail" style="font-size:0.8rem;color:rgba(255,255,255,0.5);margin-top:8px;"></div>
        </div>
    </div>
</div>

<!-- CHAT PANEL (RIGHT) -->
<div class="slide-panel right" id="chat-panel">
    <div class="panel-header">
        <h2>&#128172; AI Chat</h2>
        <div class="panel-close" onclick="toggleChatPanel()">&#10005;</div>
    </div>
    <div class="chat-messages" id="chat-messages">
        <div class="chat-msg assistant">PDF 페이지에 대해 질문해 주세요! 현재 보고 있는 페이지를 분석하고 답변해 드립니다.</div>
    </div>
    <div class="chat-input-area">
        <input type="text" id="chat-input" placeholder="질문을 입력하세요..." onkeydown="if(event.key==='Enter')sendChat()"/>
        <button onclick="sendChat()">Send</button>
    </div>
</div>

<!-- GALLERY OVERLAY -->
<div id="gallery-overlay">
    <div class="gallery-header">
        <h2>&#128218; My Fairy Tales</h2>
        <div class="panel-close" onclick="toggleGallery()">&#10005;</div>
    </div>
    <div class="gallery-body" id="gallery-body">
        <!-- Cards injected by JS -->
    </div>
</div>

<script>
// ===== STATE =====
let currentPdfKey = 'prompt';
let flipPages = [];
let currentPageIdx = 0;
let currentStoryId = null;
let pollingTimer = null;

// ===== PANEL TOGGLES =====
function toggleStoryPanel() {
    document.getElementById('story-panel').classList.toggle('open');
    document.getElementById('chat-panel').classList.remove('open');
    document.getElementById('gallery-overlay').classList.remove('open');
}
function toggleChatPanel() {
    document.getElementById('chat-panel').classList.toggle('open');
    document.getElementById('story-panel').classList.remove('open');
    document.getElementById('gallery-overlay').classList.remove('open');
}
function toggleGallery() {
    const g = document.getElementById('gallery-overlay');
    g.classList.toggle('open');
    document.getElementById('story-panel').classList.remove('open');
    document.getElementById('chat-panel').classList.remove('open');
    if (g.classList.contains('open')) loadGallery();
}

// ===== FLIPBOOK RENDERING (Canvas-based) =====
const canvas = document.getElementById('flipbook-canvas');
const ctx = canvas.getContext('2d');

function renderPage() {
    if (flipPages.length === 0) return;
    const overlay = document.getElementById('loading-overlay');
    overlay.style.display = 'none';
    const b64 = flipPages[currentPageIdx];
    if (!b64) return;
    const img = new Image();
    img.onload = function() {
        const container = document.getElementById('viewer');
        const maxW = container.clientWidth * 0.85;
        const maxH = container.clientHeight * 0.85;
        let w = img.width, h = img.height;
        const scale = Math.min(maxW / w, maxH / h, 1.5);
        w = Math.floor(w * scale);
        h = Math.floor(h * scale);
        canvas.width = w;
        canvas.height = h;
        ctx.clearRect(0, 0, w, h);
        // Shadow effect for book feel
        ctx.shadowColor = 'rgba(0,0,0,0.5)';
        ctx.shadowBlur = 20;
        ctx.shadowOffsetX = 5;
        ctx.shadowOffsetY = 5;
        ctx.drawImage(img, 0, 0, w, h);
        ctx.shadowColor = 'transparent';
    };
    img.src = 'data:image/png;base64,' + b64;
    document.getElementById('page-indicator').textContent =
        'Page ' + (currentPageIdx + 1) + ' / ' + flipPages.length;
}

function flipPrev() {
    if (currentPageIdx > 0) { currentPageIdx--; renderPage(); }
}
function flipNext() {
    if (currentPageIdx < flipPages.length - 1) { currentPageIdx++; renderPage(); }
}

// Keyboard navigation
document.addEventListener('keydown', function(e) {
    if (e.key === 'ArrowLeft') flipPrev();
    if (e.key === 'ArrowRight') flipNext();
});

// ===== LOAD BUILT-IN PDF =====
async function loadPdf(key) {
    currentPdfKey = key;
    currentPageIdx = 0;
    flipPages = [];
    document.getElementById('loading-overlay').style.display = 'flex';
    document.getElementById('loading-overlay').querySelector('p').textContent = 'Loading PDF...';
    // Update switch buttons
    document.querySelectorAll('.pdf-switch-btns button').forEach(b => {
        b.classList.toggle('active', b.dataset.key === key);
    });
    try {
        const resp = await fetch('/api/pdf/' + key + '/pages');
        const data = await resp.json();
        flipPages = data.pages || [];
        currentPageIdx = 0;
        renderPage();
    } catch(e) {
        console.error('Failed to load PDF:', e);
        document.getElementById('loading-overlay').querySelector('p').textContent = 'Failed to load PDF';
    }
}

// ===== INIT PDF SWITCH BUTTONS =====
async function initPdfButtons() {
    try {
        const resp = await fetch('/api/pdf/list');
        const pdfs = await resp.json();
        const container = document.getElementById('pdf-switch-btns');
        container.innerHTML = '';
        pdfs.forEach(p => {
            const btn = document.createElement('button');
            btn.textContent = p.label;
            btn.dataset.key = p.key;
            btn.onclick = () => loadPdf(p.key);
            if (p.key === currentPdfKey) btn.classList.add('active');
            container.appendChild(btn);
        });
    } catch(e) {
        console.error('Failed to load PDF list:', e);
    }
}

// ===== STORY GENERATION =====
async function startGeneration() {
    const btn = document.getElementById('btn-generate');
    btn.disabled = true;
    btn.textContent = 'Generating...';

    const params = {
        purpose: document.getElementById('inp-purpose').value,
        style: document.getElementById('inp-style').value,
        mood: document.getElementById('inp-mood').value,
        child_name: document.getElementById('inp-child-name').value,
        child_age: parseInt(document.getElementById('inp-child-age').value) || 7,
        child_traits: document.getElementById('inp-child-traits').value,
    };

    try {
        const resp = await fetch('/api/story/create', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(params),
        });
        const data = await resp.json();
        currentStoryId = data.story_id;

        const box = document.getElementById('progress-box');
        box.classList.add('visible');
        document.getElementById('progress-status').textContent = 'Story queued: ' + data.story_id;
        document.getElementById('progress-bar').style.width = '5%';

        // Start polling
        if (pollingTimer) clearInterval(pollingTimer);
        pollingTimer = setInterval(() => pollStatus(data.story_id), 3000);
    } catch(e) {
        console.error('Story creation failed:', e);
        btn.disabled = false;
        btn.textContent = '\u26A1 Generate Fairy Tale';
    }
}

async function pollStatus(storyId) {
    try {
        const resp = await fetch('/api/story/status/' + storyId);
        const data = await resp.json();
        const status = data.status;
        const pct = data.progress.percent || 0;

        document.getElementById('progress-status').textContent = status;
        document.getElementById('progress-bar').style.width = Math.max(pct, 5) + '%';
        document.getElementById('progress-detail').textContent =
            data.title ? ('"' + data.title + '" - ' + data.progress.done_pages + '/' + data.progress.total_pages + ' pages') : '';

        if (status.startsWith('complete') || status.startsWith('error')) {
            clearInterval(pollingTimer);
            pollingTimer = null;
            document.getElementById('btn-generate').disabled = false;
            document.getElementById('btn-generate').textContent = '\u26A1 Generate Fairy Tale';

            if (status.startsWith('complete')) {
                document.getElementById('progress-bar').style.width = '100%';
                document.getElementById('progress-status').textContent = 'Complete! Loading into FlipBook...';
                // Load into FlipBook
                loadStoryFlipbook(storyId);
            }
        }
    } catch(e) {
        console.error('Poll failed:', e);
    }
}

async function loadStoryFlipbook(storyId) {
    currentPageIdx = 0;
    flipPages = [];
    document.getElementById('loading-overlay').style.display = 'flex';
    document.getElementById('loading-overlay').querySelector('p').textContent = 'Loading Fairy Tale...';
    try {
        const resp = await fetch('/api/story/' + storyId + '/flipbook');
        const data = await resp.json();
        flipPages = data.pages || [];
        currentPageIdx = 0;
        renderPage();
        // Close story panel
        document.getElementById('story-panel').classList.remove('open');
    } catch(e) {
        console.error('Failed to load story flipbook:', e);
        document.getElementById('loading-overlay').querySelector('p').textContent = 'Failed to load story';
    }
}

// ===== GALLERY =====
async function loadGallery() {
    const body = document.getElementById('gallery-body');
    body.innerHTML = '<p style="color:var(--yellow);font-family:Bangers;font-size:1.2rem;">Loading stories...</p>';
    try {
        const resp = await fetch('/api/story/list');
        const stories = await resp.json();
        if (stories.length === 0) {
            body.innerHTML = '<p style="color:rgba(255,255,255,0.5);text-align:center;grid-column:1/-1;padding:40px;">No stories yet. Create your first fairy tale!</p>';
            return;
        }
        body.innerHTML = '';
        stories.forEach(s => {
            const card = document.createElement('div');
            card.className = 'story-card';
            let statusClass = 'queued';
            if (s.status.startsWith('complete')) statusClass = 'complete';
            else if (s.status.startsWith('error')) statusClass = 'error';
            else if (s.status !== 'queued') statusClass = 'generating';

            let thumbHtml = '<div class="placeholder">&#x1F4D6;</div>';
            if (s.thumbnail) {
                thumbHtml = '<img src="' + s.thumbnail + '" alt="thumb" onerror="this.parentElement.innerHTML=\'<div class=placeholder>&#x1F4D6;</div>\'" />';
            }

            card.innerHTML = '<div class="card-thumb">' + thumbHtml + '</div>' +
                '<div class="card-body">' +
                '<div class="card-title">' + (s.title || 'Untitled') + '</div>' +
                '<div class="card-meta">' + s.style + ' \u00B7 ' + s.mood + ' \u00B7 ' + (s.child_name || '') + ' (' + (s.child_age || '?') + ')</div>' +
                '<span class="card-status ' + statusClass + '">' + s.status + '</span>' +
                '<div class="card-actions">' +
                '<button class="btn-view" onclick="event.stopPropagation();loadStoryFlipbook(\'' + s.id + '\');toggleGallery();">View</button>' +
                (s.has_pdf ? '<button class="btn-download" onclick="event.stopPropagation();window.open(\'/api/story/' + s.id + '/pdf\',\'_blank\');">PDF</button>' : '') +
                '</div></div>';
            body.appendChild(card);
        });
    } catch(e) {
        console.error('Failed to load gallery:', e);
        body.innerHTML = '<p style="color:var(--red);">Failed to load stories.</p>';
    }
}

// ===== CHAT =====
async function sendChat() {
    const input = document.getElementById('chat-input');
    const question = input.value.trim();
    if (!question) return;
    input.value = '';

    const msgs = document.getElementById('chat-messages');
    const userMsg = document.createElement('div');
    userMsg.className = 'chat-msg user';
    userMsg.textContent = question;
    msgs.appendChild(userMsg);
    msgs.scrollTop = msgs.scrollHeight;

    // Show typing indicator
    const typing = document.createElement('div');
    typing.className = 'chat-msg assistant';
    typing.textContent = 'Thinking...';
    typing.id = 'typing-indicator';
    msgs.appendChild(typing);
    msgs.scrollTop = msgs.scrollHeight;

    try {
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                pdf_key: currentPdfKey,
                question: question,
                page_idx: currentPageIdx,
            }),
        });
        const data = await resp.json();
        typing.textContent = data.answer || 'No response.';
        typing.id = '';
    } catch(e) {
        typing.textContent = 'Error: ' + e.message;
        typing.id = '';
    }
    msgs.scrollTop = msgs.scrollHeight;
}

// ===== INIT =====
window.addEventListener('DOMContentLoaded', function() {
    initPdfButtons();
    loadPdf('prompt');
});
</script>
</body>
</html>"""

# Serve main HTML
@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=MAIN_HTML)


# ============================================================
# 15. Main Entry Point
# ============================================================
if __name__ == "__main__":
    logger.info("Starting AXIS Fairy Tale Engine + 3D FlipBook Viewer")
    logger.info("Data directory: %s", DATA_DIR)
    logger.info("DB path: %s", DB_PATH)
    logger.info("Fireworks API key set: %s", bool(FIREWORKS_API_KEY))
    logger.info("FAL key set: %s", bool(FAL_KEY))
    logger.info("HF token set: %s", bool(HF_TOKEN))
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", 7860)))
    uvicorn.run(app, host="0.0.0.0", port=7860)
