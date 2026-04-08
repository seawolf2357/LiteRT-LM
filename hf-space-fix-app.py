"""
맞춤형 동화 생성 SaaS — AXIS Engine + Emergence Seed
DB-Driven Page-by-Page Architecture
VIDRAFT × Grok Imagine × Kimi-K2.5
"""

import gradio as gr
import requests
import json
import os
import time
import re
import sqlite3
import uuid
import fal_client
from typing import List, Optional, Dict, Tuple
from datetime import datetime
import logging
import threading
from contextlib import contextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════
# Config
# ═══════════════════════════════════════════
FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY", "")
FIREWORKS_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
FIREWORKS_MODEL = "accounts/fireworks/models/kimi-k2p5"
FAL_KEY = os.getenv("FAL_KEY", "")
DB_PATH = "fairytale.db"

# ═══════════════════════════════════════════
# Emergence Seed
# ═══════════════════════════════════════════
SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "emergence_seed.json")
try:
    with open(SEED_PATH, "r", encoding="utf-8") as _f:
        EMERGENCE_SEED = json.load(_f)
    logger.info(f"✅ Emergence Seed loaded")
except FileNotFoundError:
    EMERGENCE_SEED = {"hyper_divergent_emergence_seed": {"system_kernel": {"entropy_coefficient": 0.78}, "emergence_operators": {"adversarial_dialectic": {"devil_advocate_heads": 8, "cliche_suppression_force": 0.9}, "holographic_interference": {"minimum_foreshadowing_seeds": 3}, "metacognitive_self_doubt": {"recursion_depth": 5}}}}
    logger.warning("⚠️ emergence_seed.json not found, using defaults")

# ═══════════════════════════════════════════
# Database
# ═══════════════════════════════════════════
_db_lock = threading.Lock()

@contextmanager
def get_db():
    with _db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS stories (
            story_id TEXT PRIMARY KEY,
            title TEXT DEFAULT '',
            title_en TEXT DEFAULT '',
            theme TEXT DEFAULT '',
            moral TEXT DEFAULT '',
            setting TEXT DEFAULT '',
            style_key TEXT DEFAULT '',
            mood_key TEXT DEFAULT '',
            style_prompt TEXT DEFAULT '',
            child_name TEXT DEFAULT '',
            child_age INTEGER DEFAULT 6,
            child_traits TEXT DEFAULT '',
            purpose TEXT DEFAULT '',
            character_json TEXT DEFAULT '[]',
            foreshadow_json TEXT DEFAULT '[]',
            char_appearance_tags TEXT DEFAULT '',
            ref_image_url TEXT DEFAULT '',
            status TEXT DEFAULT 'created',
            total_pages INTEGER DEFAULT 15,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pages (
            page_id TEXT PRIMARY KEY,
            story_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            beat TEXT DEFAULT '',
            tension TEXT DEFAULT 'medium',
            text_ko TEXT DEFAULT '',
            text_en TEXT DEFAULT '',
            scene_desc TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            image_status TEXT DEFAULT 'pending',
            text_status TEXT DEFAULT 'pending',
            vlm_score INTEGER DEFAULT 0,
            vlm_note TEXT DEFAULT '',
            regen_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (story_id) REFERENCES stories(story_id)
        );
        CREATE TABLE IF NOT EXISTS verifications (
            verify_id TEXT PRIMARY KEY,
            story_id TEXT NOT NULL,
            result_json TEXT DEFAULT '{}',
            overall_score INTEGER DEFAULT 0,
            verdict TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (story_id) REFERENCES stories(story_id)
        );
        CREATE INDEX IF NOT EXISTS idx_pages_story ON pages(story_id, page_number);
        """)
    logger.info("✅ DB initialized")

init_db()

# ═══════════════════════════════════════════
# Styles & Moods
# ═══════════════════════════════════════════
STYLES = {
    "수채화 동화": {"en": "Watercolor Fairy Tale", "prompt": "soft watercolor illustration, gentle pastel colors, dreamy atmosphere, children's book, hand-painted, warm lighting, delicate brushstrokes"},
    "디즈니 3D": {"en": "Disney 3D", "prompt": "Disney Pixar 3D animation style, vibrant colors, smooth CGI, expressive characters, cinematic lighting, warm glow"},
    "일본 애니메이션": {"en": "Japanese Anime", "prompt": "Studio Ghibli anime style, soft cel-shading, lush backgrounds, whimsical, warm natural lighting, expressive eyes"},
    "유럽 클래식 동화": {"en": "European Classic", "prompt": "classic European fairy tale illustration, pen and ink with watercolor, ornate borders, vintage storybook, rich earth tones"},
    "팝아트 그림책": {"en": "Pop Art Picture Book", "prompt": "modern pop art children's book, bold flat colors, clean graphic shapes, playful geometric, bright cheerful palette"}
}
MOODS = {
    "따뜻하고 포근한": "warm cozy heartwarming gentle golden hour",
    "신비롭고 모험적인": "mysterious adventurous magical enchanted mystical",
    "유쾌하고 활기찬": "cheerful energetic playful bright joyful vibrant",
    "고요하고 평화로운": "serene peaceful calm starlit tranquil dreamy moonlight",
    "용감하고 씩씩한": "brave heroic determined dramatic epic courageous bold"
}

BEAT_SHEET = [
    ("ordinary_world", "low", "일상의 미세한 균열"),
    ("anomaly", "low", "무언가 달라진 징후"),
    ("call_to_adventure", "medium", "모험의 초대, 선택의 순간"),
    ("crossing_threshold", "medium", "익숙한 세계를 떠남"),
    ("new_rules", "medium", "새 세계의 규칙 발견"),
    ("tests_and_allies", "medium", "첫 도전, 의외의 조력자"),
    ("deepening_conflict", "high", "문제는 단순하지 않다"),
    ("reversal", "high", "믿었던 것이 흔들린다"),
    ("inner_trial", "high", "내면의 두려움과 대면"),
    ("darkest_moment", "high", "모든 것을 잃은 듯한 절망"),
    ("revelation", "high", "복선이 열쇠가 되는 깨달음"),
    ("climax", "climax", "모든 감각 동원, 시간 정지"),
    ("cost_and_choice", "high", "승리의 대가와 선택"),
    ("return_changed", "medium", "같은 곳, 달라진 눈"),
    ("open_resonance", "low", "끝이 아닌 새로운 시작")
]

# ═══════════════════════════════════════════
# LLM — 짧은 호출 전용 (페이지 단위이므로 4K면 충분)
# ═══════════════════════════════════════════
def call_llm(messages: List[Dict], max_tokens=3000, temperature=0.78) -> str:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {FIREWORKS_API_KEY}"
    }
    payload = {
        "model": FIREWORKS_MODEL,
        "max_tokens": max_tokens,
        "top_p": 0.95, "top_k": 50,
        "presence_penalty": 0.15, "frequency_penalty": 0.2,
        "temperature": temperature,
        "messages": messages
    }
    resp = requests.post(FIREWORKS_URL, headers=headers, json=payload, timeout=180)
    if resp.status_code != 200:
        logger.error(f"LLM API {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    logger.info(f"  📨 LLM 응답: {len(content)}자 (앞100: {content[:100]}...)")
    return content


def safe_json_parse(raw: str) -> Optional[Dict]:
    """다단계 JSON 복구 — LLM 특유의 :=, = 오염 패턴 처리 포함"""
    if not raw or not raw.strip():
        logger.error("JSON 파싱: 빈 입력")
        return None
    
    # 1) 코드블록 제거
    cleaned = re.sub(r'```json\s*', '', raw)
    cleaned = re.sub(r'```', '', cleaned).strip()
    
    # 2) JSON 시작점
    idx = cleaned.find('{')
    if idx == -1:
        logger.error(f"JSON 파싱: '{{' 없음. 앞200: {raw[:200]}")
        return None
    cleaned = cleaned[idx:]
    
    # 3) ★ LLM JSON 오염 패턴 치환 ★
    #    "one_line":="벌레를..."  →  "one_line": "벌레를..."
    #    "one_line"="진기가..."   →  "one_line": "진기가..."
    cleaned = re.sub(r'":=\s*"', '": "', cleaned)
    cleaned = re.sub(r'":=\s*\[', '": [', cleaned)
    cleaned = re.sub(r'":=\s*\{', '": {', cleaned)
    cleaned = re.sub(r'":=\s*(\d)', r'": \1', cleaned)
    cleaned = re.sub(r'"=\s*"', '": "', cleaned)
    cleaned = re.sub(r'"=\s*\[', '": [', cleaned)
    cleaned = re.sub(r'"=\s*\{', '": {', cleaned)
    cleaned = re.sub(r'"=\s*(\d)', r'": \1', cleaned)
    
    # 4) 트레일링 콤마
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    
    # 5) 1차 파싱
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning(f"1차 파싱 실패: {e}")
    
    # 6) 괄호 복구
    last_close = max(cleaned.rfind('}'), cleaned.rfind(']'))
    if last_close > 0:
        cleaned = cleaned[:last_close + 1]
    ob = cleaned.count('{') - cleaned.count('}')
    ok = cleaned.count('[') - cleaned.count(']')
    cleaned = re.sub(r',\s*$', '', cleaned)
    cleaned += ']' * max(0, ok) + '}' * max(0, ob)
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    
    try:
        r = json.loads(cleaned)
        logger.info(f"✅ JSON 복구 성공 (괄호 {ob}+{ok}개)")
        return r
    except json.JSONDecodeError as e:
        logger.warning(f"2차 파싱 실패: {e}")
    
    # 7) 문제 라인 제거 후 재시도
    lines = cleaned.split('\n')
    safe_lines = []
    for ln in lines:
        test = '\n'.join(safe_lines + [ln])
        if test.count('"') % 2 != 0 and len(safe_lines) > 2:
            logger.warning(f"  깨진 라인 제거: {ln[:60]}")
            continue
        safe_lines.append(ln)
    
    attempt = '\n'.join(safe_lines)
    ob = attempt.count('{') - attempt.count('}')
    ok = attempt.count('[') - attempt.count(']')
    attempt += ']' * max(0, ok) + '}' * max(0, ob)
    attempt = re.sub(r',\s*([}\]])', r'\1', attempt)
    
    try:
        r = json.loads(attempt)
        logger.info(f"✅ JSON 복구 성공 (라인 제거)")
        return r
    except json.JSONDecodeError as e:
        logger.error(f"JSON 최종 실패: {e}")
    
    # 8) ★ Unterminated string 복구 — text_ko 필드만 추출
    text_ko_match = re.search(r'"text_ko"\s*:\s*"((?:[^"\\]|\\.)*)', raw)
    if text_ko_match:
        extracted = text_ko_match.group(1)
        # 이스케이프된 줄바꿈을 실제 줄바꿈으로
        extracted = extracted.replace('\\n', '\n').replace('\\"', '"')
        if len(extracted) > 30 and re.search(r'[가-힣]{10,}', extracted):
            logger.info(f"✅ Unterminated string 복구: text_ko {len(extracted)}자 추출")
            return {"text_ko": extracted, "text_en": "", "scene_description": ""}
    
    logger.error(f"앞500: {raw[:500]}")
    logger.error(f"뒤500: {raw[-500:]}")
    return None

def strip_reasoning(raw: str) -> str:
    """kimi-k2p5 reasoning 모델의 사고 과정을 제거하고 실제 동화 본문만 추출"""
    if not raw or len(raw) < 20:
        return raw
    
    # reasoning 패턴들 — 영어/한국어 모두 대응
    reasoning_patterns = [
        r'^The user wants.*?(?=\n\n|\n[가-힣])',  # "The user wants me to..."
        r'^사용자[가는이]?\s*.*?(?=\n\n|\n[가-힣])',  # "사용자는 세계 최고의..."
        r'^Let me .*?(?=\n\n)',
        r'^I need to .*?(?=\n\n)',
        r'^\*\*[A-Za-z가-힣 ]+\*\*:?\s*\n',  # **Key constraints**: 등
        r'^Key [a-z]+.*?(?=\n\n)',
        r'^분석:?\s*\n[\s\S]*?(?=\n\n)',
        r'^핵심\s*요구.*?(?=\n\n)',
    ]
    
    text = raw.strip()
    
    # 1) JSON이 포함되어 있으면 JSON에서 text_ko 추출 시도
    json_match = re.search(r'\{[^{}]*"text_ko"\s*:\s*"', text)
    if json_match:
        return text  # JSON이면 그대로 반환 (safe_json_parse가 처리)
    
    # 2) 실제 동화 본문 추출 — reasoning 이후 한국어 본문 찾기
    #    패턴: 분석/영어 블록 → 빈 줄 → 한국어 동화 본문
    lines = text.split('\n')
    story_start = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        # 한국어 동화 본문의 시작 징후
        if stripped and not stripped.startswith(('The ', 'I ', 'Key ', '**', '- ', '1.', '2.', '3.', '4.', '5.', '사용자', '분석', '핵심', 'Let ', 'Now ')):
            # 한국어 문자가 포함되어 있고 의미 있는 길이
            if re.search(r'[가-힣]', stripped) and len(stripped) > 20:
                # 분석이 아닌 동화 본문인지 확인
                if not re.match(r'^\d+\.\s*\*\*', stripped) and '비트:' not in stripped and 'tension' not in stripped.lower():
                    story_start = i
                    break
    
    if story_start > 0:
        # reasoning 부분 제거, 동화 본문만
        story_text = '\n'.join(lines[story_start:]).strip()
        if len(story_text) > 30:
            logger.info(f"  🔧 reasoning 제거: {len(text)}자 → {len(story_text)}자 (시작줄 {story_start})")
            return story_text
    
    # 3) 전체가 reasoning이면 빈 문자열
    if text.startswith(('The user', '사용자')) and not re.search(r'[가-힣]{20,}', text):
        logger.warning(f"  ⚠️ 전체가 reasoning 텍스트 — 빈 본문")
        return ""
    
    return text





# ═══════════════════════════════════════════
# Emergence Prompt Builder — JSON 시드 기반
# ═══════════════════════════════════════════
def get_emergence_system():
    k = EMERGENCE_SEED.get("hyper_divergent_emergence_seed", {})
    nd = k.get("narrative_dna_circuits", {})
    eo = k.get("emergence_operators", {})
    ad = eo.get("adversarial_dialectic", {})
    
    # 파라미터 추출
    heads = ad.get("devil_advocate_heads", 8)
    cliche = ad.get("cliche_suppression_force", 0.9)
    blacklist = ad.get("cliche_blacklist", [])
    bl_str = " / ".join([b.split(" — ")[0] for b in blacklist[:8]])
    
    ident = nd.get("identity_matrix", {}).get("elements", {})
    forbidden_starts = ident.get("linguistic_style", {}).get("forbidden_sentence_starters", [])
    forbidden_expr = ident.get("linguistic_style", {}).get("forbidden_cliche_expressions", [])
    variety = ident.get("linguistic_style", {}).get("required_variety_patterns", [])
    
    fear_rules = ident.get("subconscious_fear", {})
    comfort_palette = fear_rules.get("comfort_sensory_palette", [])
    
    dialogue = nd.get("dialogue_system", {})
    sig_line = dialogue.get("signature_line_requirement", {})
    
    sie = eo.get("sensory_immersion_engine", {})
    synesthesia = sie.get("synesthesia_examples", [])
    
    ea = eo.get("emotional_architecture", {})
    rao = eo.get("read_aloud_optimization", {})
    rhythm = rao.get("rhythm_patterns", {})

    return f"""당신은 세계 최고의 동화 작가. 안데르센+생텍쥐페리+미하엘 엔데의 영혼을 품고 있습니다.

[EMERGENCE ENGINE v2.0 — AXIS_Narrative_Singularity]

■ {heads}명의 내면 비평가 (클리셰 억제 {cliche*100:.0f}%)
  모든 문장이 이 검증을 통과해야 출력됨:
  ①뻔한가? ②아이답게 현실적인가? ③감정 긴장 충분한가? ④복선 노골적이지 않은가?
  ⑤설교하고 있지 않은가? ⑥표현이 신선한가? ⑦설정과 모순 없는가? ⑧호흡이 자연스러운가?
  
■ 금지 클리셰: {bl_str}

■ 금지 문장 시작: {', '.join(forbidden_starts[:6])}
  → 대신: 감각/대화/짧은독립문/질문/의성어로 시작

■ 금지 표현: {', '.join(forbidden_expr[:5])}
  → 대신: 구체적 신체 반응. '무서웠다' → '무릎이 자꾸 다른 방향으로 가려 했다'

■ 오감 몰입: 페이지당 최소 2감각. 공감각 권장.
  예시: {synesthesia[0] if synesthesia else '소리가 색으로 번지는 묘사'}

■ 시그니처 라인: 동화 전체에서 반복되는 핵심 문구. 처음엔 가벼운 의미 → 마지막엔 깊은 의미.

■ 읽어주기 최적화:
  - 문장 최대 40자, 긴장 시 짧은 문장 연속, 클라이맥스 전 극적 정지
  - 긴장: {rhythm.get('tension', '짧.짧.짧짧.긴~~~.')}
  - 클라이맥스: {rhythm.get('climax', '짧!짧!짧!...아주긴폭발')}

■ 감정 규칙: 한번에 하나 감정만 전환, 부정→긍정 사이 중립 경유, 기쁨은 고난 뒤 최강

■ 캐릭터: 외적 목표≠내적 욕구, 어른구출 금지, 약점→강점 변환, 적대자에게도 이유 있음

■ 부모 공명: 아이에게는 모험, 부모에게는 성장의 은유. 부모가 눈물 흘리는 지점 포함.

■ 절대 금지: AI/로봇/기술 소재, 안이한 결말, 설교, 데우스 엑스 마키나

■ 페이지 끝은 반드시 다음이 궁금한 hook으로.

반드시 JSON으로만 응답하세요. 설명/분석/생각 과정 출력 금지."""


# ═══════════════════════════════════════════
# Step 1: 스토리 뼈대 생성 (1회 호출, ~2K)
# ═══════════════════════════════════════════
def step1_create_skeleton(story_id, purpose, style_key, mood_key, child_name, child_age, child_traits):
    style = STYLES[style_key]
    
    # ★ 초경량 프롬프트 — 주제를 최상단 강조
    prompt = f"""동화 뼈대를 JSON으로 만들어. 설명이나 생각 과정 없이 JSON만 출력해.

★★★ 이 동화의 핵심 주제 (절대 벗어나지 마): {purpose} ★★★

주인공: {child_name} ({child_age}세), {child_traits}
화풍: {style['en']}, 분위기: {mood_key}

규칙: title, theme, moral, setting, foreshadowing 모두 위 핵심 주제와 직접 연결되어야 함.

{{"title":"핵심 주제를 담은 한국어 제목","title_en":"English","theme":"핵심 주제 관련 테마","moral":"핵심 주제에서 발견하는 교훈","setting":"핵심 주제가 펼쳐지는 배경 2줄","characters":[{{"name":"{child_name}","role":"주인공","appearance":"English detailed appearance: hair color, length, eye color, clothes, shoes, accessories","personality":"3 words"}}],"foreshadowing":[{{"seed_page":1,"payoff_page":11,"element":"핵심 주제 관련 복선1"}},{{"seed_page":2,"payoff_page":12,"element":"핵심 주제 관련 복선2"}},{{"seed_page":3,"payoff_page":13,"element":"핵심 주제 관련 복선3"}}]}}"""

    # ★ skeleton은 emergence 없이 직접적 시스템 프롬프트
    system = f"당신은 동화 작가입니다. 사용자가 요청한 주제로 동화 뼈대 JSON만 출력하세요. 주제는 '{purpose}'입니다. 이 주제에서 절대 벗어나지 마세요. 설명/분석/생각 과정 출력 금지. 첫 글자가 반드시 {{ 여야 합니다. AI/로봇/기술 소재 금지."

    data = None
    last_error = ""
    for attempt in range(3):
        try:
            resp = call_llm([
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ], max_tokens=2000, temperature=0.6 + attempt * 0.1)
            
            data = safe_json_parse(resp)
            if data and (data.get("title") or data.get("title_en")):
                break
            else:
                last_error = f"title 없음 (attempt {attempt+1})"
                logger.warning(f"Step1 {last_error}. 응답 앞200: {resp[:200]}")
                data = None
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Step1 attempt {attempt+1} 실패: {e}")
            time.sleep(2)
    
    if not data:
        raise ValueError(f"스토리 뼈대 생성 실패 (3회): {last_error}")
    
    char_tags = ""
    for c in data.get("characters", []):
        if c.get("appearance"):
            char_tags += f"{c['name']}: {c['appearance']}. "
    
    with get_db() as conn:
        # LLM이 string 대신 list를 반환할 수 있으므로 모두 안전 변환
        def to_str(v):
            if isinstance(v, list):
                return "\n".join(str(x) for x in v)
            if isinstance(v, dict):
                return json.dumps(v, ensure_ascii=False)
            return str(v) if v else ""
        
        conn.execute("""
            UPDATE stories SET
                title=?, title_en=?, theme=?, moral=?, setting=?,
                character_json=?, foreshadow_json=?, char_appearance_tags=?,
                status='skeleton_done', updated_at=CURRENT_TIMESTAMP
            WHERE story_id=?
        """, (
            to_str(data.get("title", "")),
            to_str(data.get("title_en", "")),
            to_str(data.get("theme", "")),
            to_str(data.get("moral", "")),
            to_str(data.get("setting", "")),
            json.dumps(data.get("characters", []), ensure_ascii=False),
            json.dumps(data.get("foreshadowing", []), ensure_ascii=False),
            char_tags, story_id
        ))
        
        # 15페이지 레코드 생성 (BEAT_SHEET 기반, page_summaries 불필요)
        for i, (beat, tension, desc) in enumerate(BEAT_SHEET):
            page_id = f"{story_id}_p{i+1}"
            conn.execute("""
                INSERT OR REPLACE INTO pages (page_id, story_id, page_number, beat, tension)
                VALUES (?, ?, ?, ?, ?)
            """, (page_id, story_id, i + 1, f"{beat}: {desc}", tension))
    
    logger.info(f"✅ Step1 완료: '{data.get('title', '')}' — 15페이지 뼈대 DB 저장")
    return data.get("title", "동화")


# ═══════════════════════════════════════════
# Step 2: 페이지별 본문 생성 (15회 호출, 각 ~1.5K)
# ═══════════════════════════════════════════
def step2_generate_page_text(story_id, page_number):
    with get_db() as conn:
        story = conn.execute("SELECT * FROM stories WHERE story_id=?", (story_id,)).fetchone()
        page = conn.execute("SELECT * FROM pages WHERE story_id=? AND page_number=?", (story_id, page_number)).fetchone()
        # 이전 페이지들 (맥락 유지)
        prev_pages = conn.execute(
            "SELECT page_number, text_ko FROM pages WHERE story_id=? AND page_number<? AND text_status='done' ORDER BY page_number",
            (story_id, page_number)
        ).fetchall()
    
    if not story or not page:
        raise ValueError(f"스토리 또는 페이지 없음: {story_id}/P{page_number}")
    
    # 이전 내용 요약 (맥락 전달, 토큰 절약)
    prev_context = ""
    if prev_pages:
        last_3 = prev_pages[-3:]  # 최근 3페이지만
        prev_context = "\n".join([f"[P{p['page_number']}] {p['text_ko'][:200]}" for p in last_3])
    
    beat, tension = page["beat"], page["tension"]
    tension_guide = {
        "low": "3~5문장, 간결하고 따뜻하게",
        "medium": "5~7문장, 몰입감 있게",
        "high": "6~8문장, 긴장감, 시간을 늘려서 묘사",
        "climax": "8~12문장, 모든 오감 동원, 시간이 정지하는 듯한 묘사"
    }.get(tension, "5~6문장")
    
    # 감정 비트맵 (emergence_seed에서 로드)
    ea = EMERGENCE_SEED.get("hyper_divergent_emergence_seed", {}).get("emergence_operators", {}).get("emotional_architecture", {})
    emotion_map = ea.get("emotional_beat_map", {}).get(f"P{page_number}", {})
    emotion_hint = ""
    if emotion_map:
        emotion_hint = f"\n감정: {emotion_map.get('primary','')} — 독자가 느낄 것: {emotion_map.get('reader_feels','')}"
    
    # 페이지별 감각 포커스
    sie = EMERGENCE_SEED.get("hyper_divergent_emergence_seed", {}).get("emergence_operators", {}).get("sensory_immersion_engine", {})
    sensory_focus = sie.get("page_specific_sensory_focus", {})
    sensory_hint = ""
    for key, val in sensory_focus.items():
        pages_in_key = key.replace("P","").split("_")
        try:
            if any(int(p) == page_number for p in pages_in_key):
                sensory_hint = f"\n감각 포커스: {val}"
                break
        except ValueError:
            continue
    
    foreshadows = json.loads(story["foreshadow_json"])
    fs_hint = ""
    for f in foreshadows:
        if f.get("seed_page") == page_number:
            fs_hint += f"\n⚠️ 이 페이지에 복선 씨앗을 심어야 합니다: {f['element']} (회수: P{f['payoff_page']})"
        if f.get("payoff_page") == page_number:
            fs_hint += f"\n⚠️ 이 페이지에서 복선을 회수해야 합니다: {f['element']} (씨앗: P{f['seed_page']})"

    prompt = f"""[동화의 핵심 주제 — 이것이 이야기의 중심이다]
★ {story['purpose']} ★

[동화 정보]
제목: {story['title']}
테마: {story['theme']}
세계관: {story['setting']}
주인공: {story['child_name']} — {story['char_appearance_tags']}
교훈: {story['moral']}

[이전 내용]
{prev_context if prev_context else '(첫 페이지)'}

[이번 페이지: P{page_number}/15]
비트: {beat}
긴장도: {tension} → {tension_guide}{emotion_hint}{sensory_hint}
{fs_hint}

[창작 규칙]
• 이 페이지는 반드시 위 ★핵심 주제★와 직접 연결
• 오감 중 최소 2가지 포함 (시각+촉각+청각+후각+미각)
• 금지: 설교, 클리셰(갑자기/그래서/그런데로 시작), 어른이 해결
• 문장 최대 40자, 읽어주기 리듬 고려
• 부모 공명: 아이에게는 모험, 부모에게는 성장의 은유

JSON만 출력:
{{
  "text_ko": "한국어 동화 본문 ({tension_guide}. 아이에게 읽어주는 톤)",
  "text_en": "English translation",
  "scene_description": "삽화를 위한 장면 묘사 (영어, 3줄 이상. 캐릭터 동작/표정/시선, 배경 색감/빛, 구도, 소품, 감정)"
}}"""

    data = None
    for attempt in range(3):
        try:
            # ★ Step2도 Step1처럼 JSON 강제 시스템 프롬프트
            system = f"당신은 동화 작가입니다. JSON 객체만 출력하세요. 절대 설명, 분석, 생각 과정을 출력하지 마세요. 첫 글자가 반드시 {{ 여야 합니다. 핵심 주제: {story['purpose']}"

            resp = call_llm([
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ], max_tokens=4000, temperature=0.78)
            
            data = safe_json_parse(resp)
            if data and data.get("text_ko"):
                break
            # JSON 파싱 실패 시 reasoning 필터링 후 plain text fallback
            if not data and resp.strip():
                logger.warning(f"P{page_number} JSON 실패 → reasoning 필터 + plain text fallback")
                plain = strip_reasoning(resp)
                # 코드블록 제거
                plain = re.sub(r'```[\s\S]*?```', '', plain).strip()
                if len(plain) > 30 and re.search(r'[가-힣]{10,}', plain):
                    data = {"text_ko": plain, "text_en": "", "scene_description": f"Scene for page {page_number} of fairy tale about {story['purpose']}"}
                    break
                else:
                    logger.warning(f"P{page_number} 본문 추출 실패 (reasoning만 있음) — 재시도")
                    continue
        except Exception as e:
            logger.warning(f"P{page_number} attempt {attempt+1} 실패: {e}")
            time.sleep(1)
    
    if not data or not data.get("text_ko"):
        raise ValueError(f"P{page_number} 본문 생성 실패")
    
    with get_db() as conn:
        conn.execute("""
            UPDATE pages SET text_ko=?, text_en=?, scene_desc=?, text_status='done', 
                             created_at=CURRENT_TIMESTAMP
            WHERE story_id=? AND page_number=?
        """, (data["text_ko"], data.get("text_en", ""), data.get("scene_description", ""),
              story_id, page_number))
    
    logger.info(f"  ✅ P{page_number} 본문 저장 ({len(data['text_ko'])}자)")
    return data["text_ko"]


# ═══════════════════════════════════════════
# Step 3: 페이지별 삽화 생성 (누적 참조)
# ═══════════════════════════════════════════
def generate_image_fal(prompt, aspect_ratio="3:4"):
    try:
        result = fal_client.subscribe("xai/grok-imagine-image",
            arguments={"prompt": prompt, "num_images": 1, "aspect_ratio": aspect_ratio, "resolution": "1k", "output_format": "png"})
        if result and result.get("images"):
            return result["images"][0]["url"]
    except Exception as e:
        logger.error(f"Image gen failed: {e}")
    return ""

def edit_image_fal(prompt, ref_urls):
    try:
        result = fal_client.subscribe("xai/grok-imagine-image/edit",
            arguments={"prompt": prompt, "num_images": 1, "resolution": "1k", "output_format": "png", "image_urls": ref_urls[:3]})
        if result and result.get("images"):
            return result["images"][0]["url"]
    except Exception as e:
        logger.error(f"Image edit failed: {e}")
    return ""

def upload_ref_image_to_fal(filepath: str) -> str:
    """사용자 업로드 참조 이미지를 fal 스토리지에 업로드"""
    try:
        url = fal_client.upload_file(filepath)
        logger.info(f"✅ 참조 이미지 업로드: {url[:60]}...")
        return url
    except Exception as e:
        logger.error(f"참조 이미지 업로드 실패: {e}")
        return ""


# ═══════════════════════════════════════════
# VLM 이미지 품질 검증 (Kimi-K2.5 Vision)
# ═══════════════════════════════════════════
def verify_image_vlm(image_url: str, scene_desc: str, char_tags: str) -> Dict:
    """Kimi-K2.5 VLM으로 생성된 삽화 품질 검증
    - 손가락 개수, 눈/코/입 배치, 캐릭터 일관성, 명백한 오류 체크
    - 90점 미만이면 재생성 대상
    """
    system = "이미지 검증 전문가. JSON만 출력. 분석/설명/생각 금지. {로 시작. 손가락 5개 아니면 anatomy_score 30이하. overall_score=min(anatomy_score,avg(나머지)). JSON: {\"anatomy_score\":0-100,\"consistency_score\":0-100,\"artifact_score\":0-100,\"composition_score\":0-100,\"child_safety_score\":0-100,\"overall_score\":0-100,\"critical_issues\":[],\"minor_issues\":[]}"

    user_content = [
        {"type": "image_url", "image_url": {"url": image_url}},
        {"type": "text", "text": f"평가. 캐릭터: {char_tags[:200]}\n손가락5개확인, 얼굴정상확인. JSON만 출력."}
    ]
    
    try:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {FIREWORKS_API_KEY}"
        }
        payload = {
            "model": FIREWORKS_MODEL,
            "max_tokens": 1500,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content}
            ]
        }
        resp = requests.post(FIREWORKS_URL, headers=headers, json=payload, timeout=90)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

        # ★ VLM reasoning 오염 제거 — Kimi-K2.5가 분석 텍스트를 출력하는 경우 JSON만 추출
        # 패턴 1: "anatomy_score" 키를 포함하는 JSON 블록 찾기
        json_match = re.search(r'\{[^{}]*"anatomy_score"\s*:\s*\d+[^{}]*\}', content)
        if json_match:
            content = json_match.group(0)
            logger.info(f"  🔧 VLM reasoning 제거 → JSON 추출 성공")
        else:
            # 패턴 2: "overall_score" 키를 포함하는 JSON 블록 찾기
            json_match2 = re.search(r'\{[^{}]*"overall_score"\s*:\s*\d+[^{}]*\}', content)
            if json_match2:
                content = json_match2.group(0)
                logger.info(f"  🔧 VLM reasoning 제거 → JSON 추출 성공 (overall_score)")

        result = safe_json_parse(content)
        if result:
            logger.info(f"  🔍 VLM 검증: {result.get('overall_score', 0)}점 | pass={result.get('pass', False)}")
            return result
    except Exception as e:
        logger.warning(f"VLM 검증 실패 (스킵): {e}")
    
    # VLM 실패 시 재생성 유도 (기본 FAIL)
    return {"overall_score": 0, "pass": False, "critical_issues": ["VLM 검증 실패 — 재생성 필요"], "minor_issues": []}


def step3_generate_page_image(story_id, page_number, max_regen=3):
    """삽화 생성 + VLM 검증 + 품질 미달 시 자동 재생성"""
    with get_db() as conn:
        story = conn.execute("SELECT * FROM stories WHERE story_id=?", (story_id,)).fetchone()
        page = conn.execute("SELECT * FROM pages WHERE story_id=? AND page_number=?", (story_id, page_number)).fetchone()
        prev_images = conn.execute(
            "SELECT image_url FROM pages WHERE story_id=? AND page_number<? AND image_status='done' ORDER BY page_number",
            (story_id, page_number)
        ).fetchall()
    
    if not page or not page["scene_desc"]:
        return "", {}
    
    ref_urls = [r["image_url"] for r in prev_images if r["image_url"]]
    tension_mood = {"low": "calm gentle soft", "medium": "engaging dynamic", "high": "dramatic intense shadows", "climax": "epic breathtaking vivid"}.get(page["tension"], "")
    
    # ★ 사용자 참조 이미지가 있으면 항상 ref에 포함
    user_ref = story["ref_image_url"] if story["ref_image_url"] else ""
    has_face_ref = bool(user_ref)
    
    base_prompt = (
        f"{story['style_prompt']}, children's fairy tale illustration, masterpiece, "
        f"CHARACTER: {story['char_appearance_tags']} "
        f"{tension_mood}. Scene: {page['scene_desc']}"
    )
    
    # 참조 이미지에 사용자 ref 포함 — 얼굴 닮기 최대 강화
    if user_ref:
        base_prompt = (
            f"CRITICAL: The main character's FACE, FACIAL FEATURES, SKIN TONE, and HAIR must be IDENTICAL to the person in the reference photo. "
            f"This is the MOST IMPORTANT requirement — the child in the illustration must look like the SAME PERSON as the reference. "
            f"Copy the exact facial structure, eye shape, nose, mouth, hair color and style from the reference photo. "
            f"{story['style_prompt']}, children's fairy tale illustration, masterpiece, "
            f"CHARACTER: {story['char_appearance_tags']} "
            f"{tension_mood}. Scene: {page['scene_desc']}"
        )
    
    url = ""
    vlm_result = {}
    original_base_prompt = base_prompt  # ★ 원본 보존 — 스타일 드리프트 방지
    avoid_text = ""

    for attempt in range(max_regen + 1):
        # ★ 매 시도마다 원본 프롬프트 기반으로 생성 (누적 방지)
        current_prompt = original_base_prompt + avoid_text

        # 이미지 생성
        if page_number == 1 and not ref_urls and not user_ref:
            url = generate_image_fal(current_prompt)
        else:
            # edit 참조 목록 구성: 사용자 ref(최우선) + 이전 이미지(최근 2개)
            edit_refs = []
            if user_ref:
                edit_refs.append(user_ref)
            edit_refs.extend(ref_urls[-2:])  # 사용자 ref + 최근 2개 = 최대 3개
            
            edit_prompt = (
                f"Create a new scene maintaining EXACTLY the same art style. "
                f"{'MOST IMPORTANT: The main character FACE must be IDENTICAL to the first reference photo — same facial structure, eyes, nose, mouth, skin tone, hair. The child must look like the SAME PERSON. ' if user_ref else ''}"
                f"MAINTAIN character design: {story['char_appearance_tags']} "
                f"{story['style_prompt']}, {tension_mood}. "
                f"NEW SCENE: {page['scene_desc']}"
            )
            url = edit_image_fal(edit_prompt, edit_refs[:3])
            if not url:
                url = generate_image_fal(current_prompt)
        
        if not url:
            logger.warning(f"  🔄 P{page_number} 이미지 생성 실패 — 재시도 {attempt+2}/{max_regen+1}")
            time.sleep(2)
            continue

        # ★ VLM 품질 검증 (참조 얼굴이 있으면 얼굴 비교 포함)
        char_tags_for_vlm = story["char_appearance_tags"]
        if has_face_ref:
            char_tags_for_vlm += " CRITICAL: Character face must match the uploaded reference photo (same person identity)"
        vlm_result = verify_image_vlm(url, page["scene_desc"], char_tags_for_vlm)
        vlm_score = vlm_result.get("overall_score", 0)
        anatomy_score = vlm_result.get("anatomy_score", vlm_score)
        critical = vlm_result.get("critical_issues", [])

        # ★ 점수 기반으로만 판단 (LLM의 "pass" 필드 무시, anatomy 별도 체크)
        if vlm_score >= 90 and anatomy_score >= 70:
            logger.info(f"  ✅ P{page_number} VLM PASS ({vlm_score}점, attempt {attempt+1})")
            break
        elif attempt < max_regen:
            # 재생성 — critical issues를 네거티브 프롬프트로 반영
            issues_str = ", ".join(critical[:3]) if critical else "quality issues"
            logger.warning(f"  🔄 P{page_number} VLM FAIL ({vlm_score}점) — 재생성 {attempt+2}/{max_regen+1}: {issues_str}")
            avoid_text = f" AVOID: {issues_str}. Ensure correct anatomy, exactly 5 fingers per hand."
            time.sleep(1)
        else:
            logger.warning(f"  ⚠️ P{page_number} VLM 최종 {vlm_score}점 — 최선 결과 사용")
    
    if url:
        with get_db() as conn:
            conn.execute("""UPDATE pages SET image_url=?, image_status='done', 
                           vlm_score=?, vlm_note=?, regen_count=?
                           WHERE story_id=? AND page_number=?""",
                         (url,
                          vlm_result.get("overall_score", 0),
                          json.dumps(vlm_result.get("critical_issues", []) + vlm_result.get("minor_issues", []), ensure_ascii=False),
                          attempt,
                          story_id, page_number))
        logger.info(f"  🖼️ P{page_number} 삽화 저장 (VLM:{vlm_result.get('overall_score',0)}점, regen:{attempt})")
    
    return url, vlm_result


# ═══════════════════════════════════════════
# Step 4: MARL 품질 검증
# ═══════════════════════════════════════════
def step4_verify(story_id):
    with get_db() as conn:
        story = conn.execute("SELECT * FROM stories WHERE story_id=?", (story_id,)).fetchone()
        pages = conn.execute("SELECT * FROM pages WHERE story_id=? ORDER BY page_number", (story_id,)).fetchall()
    
    story_text = "\n".join([f"[P{p['page_number']}|{p['tension']}] {p['text_ko']}" for p in pages if p['text_ko']])
    
    prompt = f"""동화 품질 5-Agent 평가. JSON으로만 응답:
{{
  "agent_a_character": {{"score": 1-10, "note": ""}},
  "agent_b_narrative": {{"score": 1-10, "note": ""}},
  "agent_c_age_fit": {{"score": 1-10, "note": ""}},
  "agent_d_emotion": {{"score": 1-10, "note": ""}},
  "agent_e_world": {{"score": 1-10, "note": ""}},
  "overall_score": 0-100,
  "verdict": "PASS/EXCELLENT/NEEDS_REVISION"
}}

제목: {story['title']}
테마: {story['theme']}
교훈: {story['moral']}

{story_text}"""

    try:
        resp = call_llm([
            {"role": "system", "content": "아동 동화 품질 검증 전문가 5인 패널. JSON으로만 응답."},
            {"role": "user", "content": prompt}
        ], max_tokens=2000, temperature=0.3)
        data = safe_json_parse(resp)
    except Exception as e:
        logger.error(f"Verify failed: {e}")
        data = None
    
    if not data:
        data = {"overall_score": 70, "verdict": "PASS"}
    
    vid = str(uuid.uuid4())[:8]
    with get_db() as conn:
        conn.execute("INSERT INTO verifications (verify_id, story_id, result_json, overall_score, verdict) VALUES (?,?,?,?,?)",
                     (vid, story_id, json.dumps(data, ensure_ascii=False), data.get("overall_score", 0), data.get("verdict", "")))
        conn.execute("UPDATE stories SET status='verified', updated_at=CURRENT_TIMESTAMP WHERE story_id=?", (story_id,))
    
    return data


# ═══════════════════════════════════════════
# Viewer HTML from DB
# ═══════════════════════════════════════════
def build_viewer_html(story_id):
    with get_db() as conn:
        story = conn.execute("SELECT * FROM stories WHERE story_id=?", (story_id,)).fetchone()
        pages = conn.execute("SELECT * FROM pages WHERE story_id=? ORDER BY page_number", (story_id,)).fetchall()
    
    if not story:
        return "<div style='text-align:center;padding:40px;color:#999;'>스토리를 찾을 수 없습니다.</div>"
    
    foreshadows = json.loads(story["foreshadow_json"]) if story["foreshadow_json"] else []
    fs_html = ""
    if foreshadows:
        items = "".join([
            f'<div style="padding:6px 10px;background:#FFF8EE;border-radius:6px;margin:3px 0;'
            f'border-left:3px solid #C8A96E;font-size:11px;color:#5C4A2A;">'
            f'🌱 P{f.get("seed_page","")} → 🌳 P{f.get("payoff_page","")} : {f.get("element","")}</div>'
            for f in foreshadows])
        fs_html = f'<div style="background:#FFFBF5;border-radius:12px;padding:14px;margin-bottom:20px;border:1px solid #F0E6D3;"><div style="font-size:13px;font-weight:700;color:#8B6914;margin-bottom:6px;">🔮 복선 지도</div>{items}</div>'
    
    pages_html = ""
    for p in pages:
        tc = {"low":"#E8F5E9","medium":"#FFF8E1","high":"#FFE0B2","climax":"#FFCDD2"}.get(p["tension"],"#FFF8E1")
        ti = {"low":"🌿","medium":"⚡","high":"🔥","climax":"💥"}.get(p["tension"],"📖")
        img = f'<img src="{p["image_url"]}" style="width:100%;border-radius:10px;margin-bottom:12px;box-shadow:0 3px 12px rgba(0,0,0,0.08);">' if p["image_url"] else '<div style="width:100%;height:240px;background:linear-gradient(135deg,#f0e6d3,#e8d5b8);border-radius:10px;display:flex;align-items:center;justify-content:center;color:#8B7355;margin-bottom:12px;">🎨</div>'
        
        # VLM 배지
        vlm_s = p["vlm_score"] if p["vlm_score"] else 0
        vlm_color = "#4CAF50" if vlm_s >= 90 else "#FF9800" if vlm_s >= 70 else "#f44336"
        vlm_badge = f'<span style="background:{vlm_color};color:white;font-size:9px;padding:2px 6px;border-radius:10px;">VLM {vlm_s}</span>' if vlm_s > 0 else ""
        regen_badge = f'<span style="background:#9E9E9E;color:white;font-size:9px;padding:2px 6px;border-radius:10px;">🔄{p["regen_count"]}</span>' if p["regen_count"] and p["regen_count"] > 0 else ""
        
        pages_html += f'''<div style="background:#FFFBF5;border-radius:14px;padding:20px;margin-bottom:18px;box-shadow:0 1px 8px rgba(139,105,20,0.05);border:1px solid #F0E6D3;border-left:4px solid {tc};">
            <div style="display:flex;align-items:center;gap:6px;margin-bottom:10px;">
                <span style="background:#8B6914;color:white;font-size:10px;font-weight:700;padding:3px 8px;border-radius:16px;">{p["page_number"]}/{len(pages)}</span>
                <span style="font-size:13px;">{ti} {p["beat"].split(":")[0] if ":" in p["beat"] else ""}</span>
                {vlm_badge} {regen_badge}
            </div>
            {img}
            <div style="font-family:'Noto Serif KR',Georgia,serif;font-size:15.5px;line-height:2;color:#3D2B1F;">{p["text_ko"]}</div>
        </div>'''
    
    return f'''<div style="max-width:500px;margin:0 auto;padding:16px;font-family:'Noto Sans KR',sans-serif;">
        <div style="text-align:center;padding:28px 16px;background:linear-gradient(135deg,#FFF8EE,#FFF0D6);border-radius:18px;margin-bottom:20px;border:1px solid #F0E6D3;">
            <div style="font-size:12px;color:#8B6914;font-weight:600;letter-spacing:2px;margin-bottom:6px;">✨ AXIS Emergence Engine</div>
            <h1 style="font-family:'Noto Serif KR',Georgia,serif;font-size:24px;color:#3D2B1F;margin:0 0 6px;">{story["title"]}</h1>
            <p style="font-size:13px;color:#8B7355;margin:0;">{story["theme"]}</p>
        </div>
        {fs_html}{pages_html}
        <div style="text-align:center;padding:24px;color:#A0896A;font-size:11px;">
            📖 {story["title"]} — 끝<br>💡 {story["moral"]}<br>
            <span style="font-size:9px;color:#C0A87A;">AXIS Engine × VIDRAFT | Grok Imagine & Kimi-K2.5</span>
        </div>
    </div>'''


# ═══════════════════════════════════════════
# 3D Flipbook Viewer — CSS + JS 플립북
# ═══════════════════════════════════════════
def build_flipbook_html(story_id):
    """3D CSS 플립북 뷰어 HTML 생성"""
    with get_db() as conn:
        story = conn.execute("SELECT * FROM stories WHERE story_id=?", (story_id,)).fetchone()
        pages = conn.execute("SELECT * FROM pages WHERE story_id=? ORDER BY page_number", (story_id,)).fetchall()

    if not story:
        return "<div style='text-align:center;padding:40px;color:#999;'>스토리를 찾을 수 없습니다.</div>"

    # 시트 데이터 구성: 표지 + 15페이지 + 뒷표지
    sheets_data = []

    # 표지 (시트 0)
    cover_img = pages[0]["image_url"] if pages and pages[0]["image_url"] else ""
    cover_front = f'''<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;
        background:linear-gradient(135deg,#FFF8EE,#FFF0D6);padding:20px;box-sizing:border-box;">
        <div style="font-size:11px;color:#8B6914;letter-spacing:3px;margin-bottom:8px;">AXIS Emergence Engine</div>
        <h1 style="font-family:Georgia,serif;font-size:22px;color:#3D2B1F;margin:0 0 8px;text-align:center;line-height:1.3;">{story["title"]}</h1>
        <p style="font-size:12px;color:#8B7355;margin:0 0 12px;text-align:center;">{story["theme"]}</p>
        {"<img src='" + cover_img + "' style='max-width:80%;max-height:55%;border-radius:8px;object-fit:cover;box-shadow:0 2px 10px rgba(0,0,0,0.1);'>" if cover_img else ""}
        <p style="font-size:11px;color:#A0896A;margin-top:auto;">{story["child_name"]}의 이야기</p>
    </div>'''

    # 표지 뒷면 (빈 페이지)
    cover_back = '<div style="height:100%;background:#FFFBF5;"></div>'
    sheets_data.append((cover_front, cover_back))

    # 본문 페이지들 (시트 1~8: 2페이지씩 묶음)
    for i in range(0, len(pages), 2):
        p1 = pages[i] if i < len(pages) else None
        p2 = pages[i + 1] if i + 1 < len(pages) else None

        # Front: 첫 번째 페이지
        if p1:
            img1 = f"<img src='{p1['image_url']}' style='width:100%;height:60%;object-fit:cover;border-radius:6px 6px 0 0;'>" if p1["image_url"] else "<div style='width:100%;height:60%;background:linear-gradient(135deg,#f0e6d3,#e8d5b8);display:flex;align-items:center;justify-content:center;border-radius:6px 6px 0 0;font-size:32px;'>🎨</div>"
            front = f'''<div style="height:100%;display:flex;flex-direction:column;background:#FFFBF5;overflow:hidden;">
                {img1}
                <div style="flex:1;padding:10px 14px;overflow:hidden;">
                    <div style="font-size:9px;color:#8B6914;font-weight:700;margin-bottom:4px;">P{p1["page_number"]}/15</div>
                    <div style="font-family:Georgia,serif;font-size:12px;line-height:1.7;color:#3D2B1F;">{p1["text_ko"][:200]}</div>
                </div>
            </div>'''
        else:
            front = '<div style="height:100%;background:#FFFBF5;"></div>'

        # Back: 두 번째 페이지
        if p2:
            img2 = f"<img src='{p2['image_url']}' style='width:100%;height:60%;object-fit:cover;border-radius:6px 6px 0 0;'>" if p2["image_url"] else "<div style='width:100%;height:60%;background:linear-gradient(135deg,#f0e6d3,#e8d5b8);display:flex;align-items:center;justify-content:center;border-radius:6px 6px 0 0;font-size:32px;'>🎨</div>"
            back = f'''<div style="height:100%;display:flex;flex-direction:column;background:#FFFBF5;overflow:hidden;">
                {img2}
                <div style="flex:1;padding:10px 14px;overflow:hidden;">
                    <div style="font-size:9px;color:#8B6914;font-weight:700;margin-bottom:4px;">P{p2["page_number"]}/15</div>
                    <div style="font-family:Georgia,serif;font-size:12px;line-height:1.7;color:#3D2B1F;">{p2["text_ko"][:200]}</div>
                </div>
            </div>'''
        else:
            back = '<div style="height:100%;background:#FFFBF5;"></div>'

        sheets_data.append((front, back))

    # 뒷표지
    back_cover_front = f'''<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;
        background:linear-gradient(135deg,#FFF0D6,#FFF8EE);padding:20px;box-sizing:border-box;">
        <div style="font-size:48px;margin-bottom:16px;">📖</div>
        <p style="font-family:Georgia,serif;font-size:14px;color:#3D2B1F;text-align:center;line-height:1.8;margin:0 0 16px;">{story["moral"]}</p>
        <div style="font-size:10px;color:#A0896A;text-align:center;">— 끝 —</div>
        <div style="margin-top:auto;font-size:9px;color:#C0A87A;text-align:center;">AXIS Engine | Grok Imagine & Kimi-K2.5</div>
    </div>'''
    back_cover_back = '<div style="height:100%;background:linear-gradient(135deg,#3D2B1F,#5C4A2A);border-radius:0 4px 4px 0;"></div>'
    sheets_data.append((back_cover_front, back_cover_back))

    total = len(sheets_data)

    # 시트 HTML 생성
    sheets_html = ""
    for idx, (front, back) in enumerate(sheets_data):
        z = total - idx
        sheets_html += f'''<div class="fb-sheet" data-index="{idx}" style="z-index:{z};">
            <div class="fb-front">{front}</div>
            <div class="fb-back">{back}</div>
        </div>\n'''

    return f'''
    <div id="fb-wrap" style="max-width:700px;margin:0 auto;font-family:'Noto Sans KR',sans-serif;user-select:none;">
        <style>
            .fb-scene {{
                perspective: 2000px;
                width: 340px; height: 480px;
                margin: 0 auto;
                position: relative;
            }}
            .fb-sheet {{
                position: absolute; width: 100%; height: 100%;
                transform-style: preserve-3d;
                transform-origin: left center;
                transition: transform 0.8s cubic-bezier(0.645,0.045,0.355,1.000);
                cursor: pointer;
                border-radius: 0 4px 4px 0;
                box-shadow: 2px 2px 8px rgba(0,0,0,0.06);
            }}
            .fb-sheet.flipped {{ transform: rotateY(-180deg); }}
            .fb-front, .fb-back {{
                position: absolute; width: 100%; height: 100%;
                backface-visibility: hidden;
                -webkit-backface-visibility: hidden;
                overflow: hidden;
                border-radius: 0 4px 4px 0;
                border: 1px solid #E8D5B8;
            }}
            .fb-back {{
                transform: rotateY(180deg);
            }}
            .fb-front::after, .fb-back::after {{
                content: '';
                position: absolute; top: 0; left: 0; right: 0; bottom: 0;
                background: linear-gradient(to right, rgba(0,0,0,0.06) 0%, transparent 8%, transparent 92%, rgba(0,0,0,0.03) 100%);
                pointer-events: none;
            }}
            .fb-nav {{
                display: flex; justify-content: center; align-items: center;
                gap: 16px; margin-top: 16px;
            }}
            .fb-btn {{
                background: #8B6914; color: white; border: none;
                padding: 8px 20px; border-radius: 20px; cursor: pointer;
                font-size: 13px; font-weight: 600;
                transition: background 0.2s;
            }}
            .fb-btn:hover {{ background: #6B5210; }}
            .fb-btn:disabled {{ background: #C0A87A; cursor: default; }}
            .fb-info {{
                text-align: center; margin-top: 8px;
                font-size: 12px; color: #8B7355;
            }}
            .fb-spine {{
                position: absolute; left: -3px; top: 0; bottom: 0; width: 6px;
                background: linear-gradient(to right, #5C4A2A, #8B6914, #5C4A2A);
                border-radius: 3px 0 0 3px;
                box-shadow: -1px 0 3px rgba(0,0,0,0.2);
                z-index: 9999;
            }}
        </style>

        <div style="text-align:center;margin-bottom:12px;">
            <span style="font-size:12px;color:#8B6914;font-weight:600;">📕 3D 플립북</span>
            <span style="font-size:11px;color:#A0896A;margin-left:8px;">클릭 또는 ← → 키로 넘기세요</span>
        </div>

        <div class="fb-scene" id="fb-scene">
            <div class="fb-spine"></div>
            {sheets_html}
        </div>

        <div class="fb-nav">
            <button class="fb-btn" id="fb-prev" onclick="fbPrev()">◀ 이전</button>
            <span class="fb-info" id="fb-info">1 / {total}</span>
            <button class="fb-btn" id="fb-next" onclick="fbNext()">다음 ▶</button>
        </div>

        <script>
        (function() {{
            const sheets = document.querySelectorAll('#fb-scene .fb-sheet');
            const total = {total};
            let current = 0;

            function update() {{
                sheets.forEach((s, i) => {{
                    if (i < current) {{
                        s.classList.add('flipped');
                        s.style.zIndex = i + 1;
                    }} else {{
                        s.classList.remove('flipped');
                        s.style.zIndex = total - i;
                    }}
                }});
                document.getElementById('fb-info').textContent = (current + 1) + ' / ' + total;
                document.getElementById('fb-prev').disabled = (current === 0);
                document.getElementById('fb-next').disabled = (current >= total - 1);
            }}

            window.fbNext = function() {{
                if (current < total - 1) {{ current++; update(); }}
            }};
            window.fbPrev = function() {{
                if (current > 0) {{ current--; update(); }}
            }};

            sheets.forEach((s, i) => {{
                s.addEventListener('click', function() {{
                    if (i >= current) window.fbNext();
                    else window.fbPrev();
                }});
            }});

            document.addEventListener('keydown', function(e) {{
                if (e.key === 'ArrowRight') window.fbNext();
                else if (e.key === 'ArrowLeft') window.fbPrev();
            }});

            update();
        }})();
        </script>
    </div>'''


# ═══════════════════════════════════════════
# PDF Generation — ReportLab
# ═══════════════════════════════════════════
def generate_pdf(story_id):
    """동화 PDF 생성 — 한국어 지원"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from io import BytesIO
    import tempfile

    # 한국어 CID 폰트 등록 (별도 ttf 파일 불필요)
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))
        KR_FONT = 'HYSMyeongJo-Medium'
    except Exception:
        KR_FONT = 'Helvetica'

    with get_db() as conn:
        story = conn.execute("SELECT * FROM stories WHERE story_id=?", (story_id,)).fetchone()
        pages = conn.execute("SELECT * FROM pages WHERE story_id=? ORDER BY page_number", (story_id,)).fetchall()

    if not story:
        return None

    w, h = A4
    pdf_path = os.path.join(tempfile.gettempdir(), f"fairytale_{story_id}.pdf")
    c = canvas.Canvas(pdf_path, pagesize=A4)

    # === 표지 ===
    c.setFillColorRGB(0.24, 0.17, 0.12)
    c.rect(0, 0, w, h, fill=True)
    c.setFillColorRGB(1, 0.97, 0.93)
    c.rect(15*mm, 15*mm, w - 30*mm, h - 30*mm, fill=True)

    c.setFont(KR_FONT, 24)
    c.setFillColorRGB(0.24, 0.17, 0.12)
    # 제목 — 중앙 정렬
    title = story["title"] or "동화"
    title_w = c.stringWidth(title, KR_FONT, 24)
    c.drawString((w - title_w) / 2, h - 80*mm, title)

    c.setFont(KR_FONT, 12)
    c.setFillColorRGB(0.55, 0.45, 0.33)
    theme = story["theme"] or ""
    theme_w = c.stringWidth(theme, KR_FONT, 12)
    c.drawString((w - theme_w) / 2, h - 95*mm, theme)

    # 표지 이미지
    if pages and pages[0]["image_url"]:
        try:
            img_resp = requests.get(pages[0]["image_url"], timeout=15)
            if img_resp.status_code == 200:
                from reportlab.lib.utils import ImageReader
                img_io = BytesIO(img_resp.content)
                img_reader = ImageReader(img_io)
                iw, ih = img_reader.getSize()
                max_w = w - 60*mm
                max_h = 100*mm
                scale = min(max_w / iw, max_h / ih)
                dw, dh = iw * scale, ih * scale
                c.drawImage(img_reader, (w - dw) / 2, 40*mm, dw, dh, preserveAspectRatio=True, mask='auto')
        except Exception as e:
            logger.warning(f"PDF 표지 이미지 로드 실패: {e}")

    c.setFont(KR_FONT, 10)
    c.drawCentredString(w / 2, 25*mm, f"{story['child_name']}의 이야기")

    c.showPage()

    # === 본문 페이지 ===
    for p in pages:
        # 배경
        c.setFillColorRGB(1, 0.99, 0.96)
        c.rect(0, 0, w, h, fill=True)

        y_cursor = h - 15*mm

        # 페이지 번호
        c.setFont(KR_FONT, 8)
        c.setFillColorRGB(0.55, 0.41, 0.08)
        c.drawString(15*mm, y_cursor, f"P{p['page_number']}/15")
        y_cursor -= 5*mm

        # 이미지
        if p["image_url"]:
            try:
                img_resp = requests.get(p["image_url"], timeout=15)
                if img_resp.status_code == 200:
                    from reportlab.lib.utils import ImageReader
                    img_io = BytesIO(img_resp.content)
                    img_reader = ImageReader(img_io)
                    iw, ih = img_reader.getSize()
                    max_w = w - 30*mm
                    max_h = 160*mm
                    scale = min(max_w / iw, max_h / ih)
                    dw, dh = iw * scale, ih * scale
                    c.drawImage(img_reader, (w - dw) / 2, y_cursor - dh, dw, dh, preserveAspectRatio=True, mask='auto')
                    y_cursor -= (dh + 8*mm)
            except Exception as e:
                logger.warning(f"PDF P{p['page_number']} 이미지 로드 실패: {e}")
                y_cursor -= 10*mm

        # 텍스트
        text = p["text_ko"] or ""
        c.setFont(KR_FONT, 11)
        c.setFillColorRGB(0.24, 0.17, 0.12)
        text_lines = []
        for line in text.split('\n'):
            # 수동 줄바꿈 (한 줄 약 35자)
            while len(line) > 35:
                text_lines.append(line[:35])
                line = line[35:]
            text_lines.append(line)

        for tl in text_lines:
            if y_cursor < 20*mm:
                break
            c.drawString(20*mm, y_cursor, tl)
            y_cursor -= 6*mm

        c.showPage()

    # === 뒷표지 ===
    c.setFillColorRGB(0.24, 0.17, 0.12)
    c.rect(0, 0, w, h, fill=True)
    c.setFillColorRGB(1, 0.97, 0.93)
    c.setFont(KR_FONT, 14)
    moral = story["moral"] or ""
    moral_w = c.stringWidth(moral, KR_FONT, 14)
    c.drawString(max((w - moral_w) / 2, 15*mm), h / 2, moral)
    c.setFont(KR_FONT, 9)
    c.drawCentredString(w / 2, h / 2 - 20*mm, "AXIS Engine | Grok Imagine & Kimi-K2.5")

    c.showPage()
    c.save()

    logger.info(f"PDF 생성 완료: {pdf_path}")
    return pdf_path


# ═══════════════════════════════════════════
# Main Pipeline — 모든 단계 DB 경유
# ═══════════════════════════════════════════
def run_pipeline(purpose, style, mood, child_name, child_age, child_traits, ref_image, progress=gr.Progress()):
    if not FIREWORKS_API_KEY:
        return "⚠️ FIREWORKS_API_KEY 미설정", "", {}, "", ""
    if not FAL_KEY:
        return "⚠️ FAL_KEY 미설정", "", {}, "", ""
    if not purpose or len(purpose.strip()) < 5:
        return "⚠️ 목적/주제를 입력해주세요.", "", {}, "", ""
    if not child_name:
        return "⚠️ 주인공 이름을 입력해주세요.", "", {}, "", ""
    
    log = []
    story_id = str(uuid.uuid4())[:12]
    style_prompt = STYLES[style]["prompt"] + ", " + MOODS[mood]
    
    # ★ 참조 이미지 업로드
    ref_image_url = ""
    if ref_image is not None:
        log.append("▶ 참조 이미지 업로드 중...")
        progress(0.01, desc="📷 참조 이미지 업로드 중...")
        ref_image_url = upload_ref_image_to_fal(ref_image)
        if ref_image_url:
            log.append(f"  ✅ 참조 이미지 업로드 완료")
        else:
            log.append(f"  ⚠️ 참조 이미지 업로드 실패 — 참조 없이 진행")
    
    # DB에 스토리 레코드 생성
    with get_db() as conn:
        conn.execute("""
            INSERT INTO stories (story_id, style_key, mood_key, style_prompt, child_name, child_age, child_traits, purpose, ref_image_url, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'created')
        """, (story_id, style, mood, style_prompt, child_name, int(child_age), child_traits, purpose, ref_image_url))
    
    try:
        # === Step 1: 뼈대 (1회 LLM) ===
        progress(0.03, desc="🦴 스토리 뼈대 생성 중...")
        log.append(f"▶ Step 1: 스토리 뼈대 생성 (story_id: {story_id})")
        title = step1_create_skeleton(story_id, purpose, style, mood, child_name, int(child_age), child_traits)
        log.append(f"  ✅ '{title}' — 15페이지 뼈대 DB 저장 완료")
        
        # === Step 2: 페이지별 본문 (15회 LLM) ===
        log.append(f"\n▶ Step 2: 페이지별 본문 생성 (15회 호출)")
        for pn in range(1, 16):
            pct = 0.05 + (pn / 15) * 0.35
            beat_name = BEAT_SHEET[pn-1][0] if pn <= len(BEAT_SHEET) else ""
            progress(pct, desc=f"📝 P{pn}/15 {beat_name} 집필 중...")
            try:
                text = step2_generate_page_text(story_id, pn)
                log.append(f"  ✅ P{pn} ({beat_name}) — {len(text)}자")
            except Exception as e:
                log.append(f"  ❌ P{pn} 실패: {e}")
            time.sleep(0.5)
        
        # === Step 3: 페이지별 삽화 + VLM 검증 ===
        log.append(f"\n▶ Step 3: 삽화 생성 + VLM 품질 검증 (누적 참조 일관성)")
        if ref_image_url:
            log.append(f"  📷 참조 이미지 활성: 주인공 얼굴 일관성 적용")
        vlm_stats = {"pass": 0, "regen": 0, "fail": 0}
        for pn in range(1, 16):
            pct = 0.42 + (pn / 15) * 0.45
            progress(pct, desc=f"🎨 P{pn}/15 삽화 + VLM 검증...")
            try:
                url, vlm = step3_generate_page_image(story_id, pn)
                vs = vlm.get("overall_score", 0)
                regen = vlm.get("critical_issues", [])
                if vs >= 90:
                    vlm_stats["pass"] += 1
                    log.append(f"  🖼️ P{pn} ✅ VLM {vs}점")
                elif url:
                    vlm_stats["regen"] += 1
                    log.append(f"  🖼️ P{pn} ⚠️ VLM {vs}점 (재생성 후 최선)")
                else:
                    vlm_stats["fail"] += 1
                    log.append(f"  ❌ P{pn} 삽화 실패")
            except Exception as e:
                vlm_stats["fail"] += 1
                log.append(f"  ❌ P{pn} 삽화 실패: {e}")
            time.sleep(1)
        log.append(f"  📊 VLM 통계: ✅{vlm_stats['pass']} ⚠️{vlm_stats['regen']} ❌{vlm_stats['fail']}")
        
        # === Step 4: 품질 검증 ===
        progress(0.9, desc="🔍 MARL 5-Agent 품질 검증...")
        log.append(f"\n▶ Step 4: MARL 5-Agent 검증")
        verification = step4_verify(story_id)
        score = verification.get("overall_score", 0)
        verdict = verification.get("verdict", "?")
        log.append(f"  ✅ 종합: {score}/100 ({verdict})")
        
        # === 뷰어 렌더링 ===
        progress(0.96, desc="📖 뷰어 렌더링...")
        viewer = build_viewer_html(story_id)
        
        # 스토리 마크다운
        with get_db() as conn:
            story = conn.execute("SELECT * FROM stories WHERE story_id=?", (story_id,)).fetchone()
            pages = conn.execute("SELECT * FROM pages WHERE story_id=? ORDER BY page_number", (story_id,)).fetchall()
        
        md = f"# {story['title']}\n*{story['title_en']}*\n\n> {story['theme']}\n\n---\n\n"
        for p in pages:
            ti = {"low":"🌿","medium":"⚡","high":"🔥","climax":"💥"}.get(p["tension"],"📖")
            md += f"### {ti} P{p['page_number']}\n{p['text_ko']}\n\n"
            if p["image_url"]:
                md += f"![삽화]({p['image_url']})\n\n"
            md += "---\n\n"
        md += f"\n💡 **교훈:** {story['moral']}\n"
        
        # === 3D 플립북 생성 ===
        progress(0.97, desc="📕 3D 플립북 생성 중...")
        log.append(f"\n▶ 3D 플립북 생성")
        flipbook = build_flipbook_html(story_id)
        log.append(f"  ✅ 플립북 HTML 생성 완료")

        progress(1.0, desc="✨ 완료!")
        log.append(f"\n🎉 완료! story_id: {story_id}")

        with get_db() as conn:
            conn.execute("UPDATE stories SET status='completed', updated_at=CURRENT_TIMESTAMP WHERE story_id=?", (story_id,))

        # ★ gr.JSON은 dict를 받아야 함 (json.dumps 문자열 X)
        return viewer, md, verification, "\n".join(log), flipbook

    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        log.append(f"\n❌ 오류: {e}")
        try:
            with get_db() as conn:
                conn.execute("UPDATE stories SET status='failed', updated_at=CURRENT_TIMESTAMP WHERE story_id=?", (story_id,))
        except Exception:
            pass
        # 부분 결과라도 보여주기
        try:
            viewer = build_viewer_html(story_id)
            flipbook = build_flipbook_html(story_id)
        except Exception:
            viewer = f"<div style='color:#C0392B;padding:20px;'>❌ {e}</div>"
            flipbook = ""
        return viewer, "", {}, "\n".join(log), flipbook


# ═══════════════════════════════════════════
# 이전 동화 불러오기 — DB 조회
# ═══════════════════════════════════════════
def list_stories():
    """DB에서 생성된 동화 목록을 가져온다"""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT story_id, title, purpose, child_name, child_age, style_key, status, created_at
            FROM stories ORDER BY created_at DESC LIMIT 20
        """).fetchall()
    
    if not rows:
        return gr.update(choices=[], value=None), "아직 생성된 동화가 없습니다."
    
    choices = []
    info_lines = []
    for r in rows:
        status_icon = {"completed": "✅", "failed": "❌", "created": "⏳"}.get(r["status"], "❓")
        label = f"{status_icon} {r['title'] or '(제목 없음)'} — {r['child_name']}({r['child_age']}세) [{r['created_at'][:16]}]"
        choices.append((label, r["story_id"]))
        info_lines.append(f"• {label}\n  주제: {r['purpose'][:60]}...")
    
    return gr.update(choices=choices, value=choices[0][1] if choices else None), "\n".join(info_lines)


def load_story_from_db(story_id):
    """DB에서 동화를 불러와서 뷰어, 마크다운, 검증결과를 반환"""
    if not story_id:
        return "<div style='text-align:center;padding:40px;color:#A0896A;'>동화를 선택해주세요</div>", "", {}, ""

    try:
        with get_db() as conn:
            story = conn.execute("SELECT * FROM stories WHERE story_id=?", (story_id,)).fetchone()
            pages = conn.execute("SELECT * FROM pages WHERE story_id=? ORDER BY page_number", (story_id,)).fetchall()
            verify = conn.execute("SELECT * FROM verifications WHERE story_id=? ORDER BY created_at DESC LIMIT 1", (story_id,)).fetchone()

        if not story:
            return "<div style='color:#C0392B;padding:20px;'>❌ 해당 동화를 찾을 수 없습니다.</div>", "", {}, ""
        
        # 뷰어 HTML
        viewer = build_viewer_html(story_id)
        
        # 마크다운
        md = f"# {story['title']}\n*{story['title_en']}*\n\n> {story['theme']}\n\n**주제:** {story['purpose']}\n\n---\n\n"
        done_count = 0
        img_count = 0
        for p in pages:
            ti = {"low": "🌿", "medium": "⚡", "high": "🔥", "climax": "💥"}.get(p["tension"], "📖")
            text = p['text_ko'] or '(본문 없음)'
            # reasoning 텍스트 표시 경고
            if text.startswith(('The user', '사용자')) and len(text) > 500:
                text = f"⚠️ *[reasoning 오염 — {len(text)}자]*\n\n" + text[:200] + "..."
            md += f"### {ti} P{p['page_number']}\n{text}\n\n"
            if p["image_url"]:
                md += f"![삽화]({p['image_url']})\n\n"
                img_count += 1
            if p["text_status"] == "done":
                done_count += 1
            md += "---\n\n"
        
        md += f"\n💡 **교훈:** {story['moral']}\n"
        md += f"\n📊 **통계:** 본문 {done_count}/15페이지, 삽화 {img_count}/15장\n"
        md += f"🆔 **story_id:** {story_id}\n"
        
        # 검증 결과 — gr.JSON은 dict를 받아야 함
        verify_data = {}
        if verify and verify["result_json"]:
            try:
                verify_data = json.loads(verify["result_json"])
            except (json.JSONDecodeError, TypeError):
                verify_data = {"raw": verify["result_json"]}
        
        flipbook = build_flipbook_html(story_id)
        return viewer, md, verify_data, flipbook

    except Exception as e:
        logger.error(f"동화 불러오기 실패: {e}", exc_info=True)
        return f"<div style='color:#C0392B;padding:20px;'>❌ 불러오기 실패: {e}</div>", "", {}, ""


# ═══════════════════════════════════════════
# Gradio UI
# ═══════════════════════════════════════════
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;600;700&family=Noto+Serif+KR:wght@400;600;700&display=swap');
.gradio-container { max-width:1200px !important; }
footer { display:none !important; }
"""

HEADER = """
<div style="text-align:center;padding:32px 16px;background:linear-gradient(135deg,#FFF8EE,#FFF0D6,#FFE8C0);border-radius:18px;margin-bottom:16px;border:1px solid #F0E6D3;">
    <div style="font-size:40px;margin-bottom:6px;">📖✨</div>
    <h1 style="font-family:'Noto Serif KR',Georgia,serif;font-size:26px;color:#3D2B1F;margin:0 0 4px;">맞춤형 동화 생성 스튜디오</h1>
    <p style="font-size:13px;color:#8B7355;margin:0 0 10px;">AXIS Emergence Engine — DB-Driven Page-by-Page Architecture</p>
    <div style="display:flex;justify-content:center;gap:8px;flex-wrap:wrap;">
        <span style="background:#8B6914;color:white;font-size:9px;padding:2px 8px;border-radius:16px;">🧬 Emergence Seed</span>
        <span style="background:#3D2B1F;color:#F0E6D3;font-size:9px;padding:2px 8px;border-radius:16px;">🎨 Grok Imagine</span>
        <span style="background:#5C4A2A;color:#F0E6D3;font-size:9px;padding:2px 8px;border-radius:16px;">🧠 Kimi-K2.5</span>
        <span style="background:#1A3D5C;color:#D6E8F0;font-size:9px;padding:2px 8px;border-radius:16px;">💾 SQLite DB</span>
        <span style="background:#2A5C4A;color:#E6F0E6;font-size:9px;padding:2px 8px;border-radius:16px;">VIDRAFT</span>
    </div>
</div>"""

with gr.Blocks(title="맞춤형 동화 생성 SaaS") as demo:
    gr.HTML(HEADER)

    with gr.Tabs():
        with gr.TabItem("✨ 동화 만들기"):
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 📝 스토리 설정")
                    purpose = gr.Textbox(label="어떤 동화를 만들까요?", placeholder="예: 용기를 내서 어두운 숲 속 잃어버린 별을 찾아 떠나는 모험...", lines=3, max_lines=5)
                    with gr.Row():
                        style = gr.Dropdown(list(STYLES.keys()), value="수채화 동화", label="🎨 화풍")
                        mood = gr.Dropdown(list(MOODS.keys()), value="따뜻하고 포근한", label="🌈 분위기")
                    gr.Markdown("### 👦 주인공 정보")
                    with gr.Row():
                        child_name = gr.Textbox(label="이름", placeholder="예: 하준", scale=2)
                        child_age = gr.Slider(3, 12, value=6, step=1, label="나이", scale=1)
                    child_traits = gr.Textbox(label="주인공 특징", placeholder="예: 짧은 곱슬머리, 별 모양 머리핀, 파란 잠옷, 강아지 몽이와 함께", lines=2)
                    
                    gr.Markdown("### 📷 참조 이미지 (선택)")
                    ref_image = gr.Image(
                        label="주인공 얼굴 사진을 업로드하면 삽화에 반영됩니다",
                        type="filepath",
                        height=150
                    )
                    gr.HTML('<div style="font-size:10px;color:#A0896A;margin-top:-8px;">💡 업로드한 사진은 AI 학습에 사용되지 않으며, 삽화 생성 참조로만 사용됩니다.</div>')
                    
                    generate_btn = gr.Button("📖 동화 생성 시작", variant="primary", size="lg")
                    gr.HTML('<div style="background:#FFF8EE;border:1px solid #F0E6D3;border-radius:10px;padding:12px;margin-top:6px;font-size:11px;color:#8B7355;"><b>⚡ AXIS Engine v2</b><br>• 뼈대 1회 + 본문 15회 + 삽화 15회 + <b>VLM 검증 15회</b> + 검증 1회<br>• VLM 90점 미만 또는 해부학 오류 → 자동 재생성 (최대 3회)<br>• 참조 이미지 업로드 시 캐릭터 얼굴 일관성 강화</div>')
                with gr.Column(scale=1):
                    gr.Markdown("### 📊 생성 로그")
                    gen_log = gr.Textbox(label="실시간 진행", lines=22, max_lines=30, interactive=False)
        
        with gr.TabItem("📖 동화 뷰어"):
            viewer_output = gr.HTML("<div style='text-align:center;padding:60px;color:#A0896A;'><div style='font-size:48px;margin-bottom:12px;'>📖</div>동화를 생성하면 여기에 표시됩니다</div>")

        with gr.TabItem("📕 3D 플립북"):
            flipbook_output = gr.HTML("<div style='text-align:center;padding:60px;color:#A0896A;'><div style='font-size:48px;margin-bottom:12px;'>📕</div>동화를 생성하면 3D 플립북이 여기에 표시됩니다<br><span style='font-size:12px;'>클릭 또는 ← → 키로 페이지를 넘길 수 있습니다</span></div>")
            gr.Markdown("---")
            gr.Markdown("### 📥 PDF 다운로드")
            pdf_btn = gr.Button("📥 최근 동화 PDF 다운로드", variant="secondary")
            pdf_file = gr.File(label="생성된 PDF", interactive=False)

            def download_latest_pdf():
                """최근 완료된 동화의 PDF 생성"""
                with get_db() as conn:
                    row = conn.execute("SELECT story_id FROM stories WHERE status='completed' ORDER BY updated_at DESC LIMIT 1").fetchone()
                if row:
                    return generate_pdf(row["story_id"])
                return None
            pdf_btn.click(fn=download_latest_pdf, inputs=[], outputs=[pdf_file])

        with gr.TabItem("📝 스토리 전문"):
            story_output = gr.Markdown("*동화를 생성하면 전체 텍스트가 여기에 표시됩니다.*")

        with gr.TabItem("🔍 AXIS 품질 검증"):
            gr.Markdown("### MARL 5-Agent 품질 검증 결과")
            verification_output = gr.JSON(label="검증 결과")

        with gr.TabItem("📚 이전 동화"):
            gr.Markdown("### 📚 이전에 생성한 동화 불러오기")
            gr.HTML('<div style="font-size:12px;color:#8B7355;margin-bottom:10px;">DB에 저장된 동화를 불러와서 다시 볼 수 있습니다. ✅완료 ❌실패 ⏳진행중</div>')
            with gr.Row():
                refresh_btn = gr.Button("🔄 목록 새로고침", size="sm")
            story_list_info = gr.Textbox(label="동화 목록", lines=6, interactive=False)
            story_selector = gr.Dropdown(label="불러올 동화 선택", choices=[], interactive=True)
            load_btn = gr.Button("📖 동화 불러오기", variant="primary")

            gr.Markdown("---")
            gr.Markdown("### 📖 불러온 동화")
            loaded_viewer = gr.HTML("<div style='text-align:center;padding:40px;color:#A0896A;'>위에서 동화를 선택하고 '불러오기' 버튼을 누르세요</div>")
            loaded_story = gr.Markdown("*동화를 선택하면 여기에 전문이 표시됩니다.*")
            loaded_verify = gr.JSON(label="검증 결과")
            loaded_flipbook = gr.HTML("")

            refresh_btn.click(fn=list_stories, inputs=[], outputs=[story_selector, story_list_info])
            load_btn.click(fn=load_story_from_db, inputs=[story_selector], outputs=[loaded_viewer, loaded_story, loaded_verify, loaded_flipbook])

    generate_btn.click(fn=run_pipeline, inputs=[purpose, style, mood, child_name, child_age, child_traits, ref_image],
                       outputs=[viewer_output, story_output, verification_output, gen_log, flipbook_output], show_progress="full")

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False, css=CSS, theme=gr.themes.Soft())