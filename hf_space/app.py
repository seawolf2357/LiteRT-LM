# ============================================================
# AI BOOK MAKER - 3D FlipBook + Fairy Tale Generator
# Integrated FastAPI Application
# ============================================================

from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
import pathlib, os, uvicorn, base64, json, uuid, time, re, sqlite3
from typing import Dict, List, Any, Optional
import asyncio
import logging
import threading
import concurrent.futures
import requests
import fitz

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE = pathlib.Path(__file__).parent
app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE), name="static")

CACHE_DIR = BASE / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
EMBEDDING_DIR = BASE / "embeddings"
EMBEDDING_DIR.mkdir(parents=True, exist_ok=True)
STORIES_DIR = BASE / "stories"
STORIES_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = BASE / "stories.db"

# ============================================================
# [1] Environment Variables
# ============================================================
FIREWORKS_API_KEY = os.getenv("FIREWORKS_API", os.getenv("FIREWORKS_API_KEY", "")).strip()
FIREWORKS_API_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
FIREWORKS_VLM_MODEL = "accounts/fireworks/models/qwen3-vl-235b-a22b-instruct"
FIREWORKS_LLM_MODEL = "accounts/fireworks/models/kimi-k2p5"
FAL_KEY = os.getenv("FAL_KEY", "").strip()
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
HAS_VALID_API_KEY = bool(FIREWORKS_API_KEY)
HAS_FAL_KEY = bool(FAL_KEY)

if FAL_KEY:
    os.environ["FAL_KEY"] = FAL_KEY

logger.info(f"API Keys: Fireworks={'OK' if HAS_VALID_API_KEY else 'MISSING'}, FAL={'OK' if HAS_FAL_KEY else 'MISSING'}, HF={'OK' if HF_TOKEN else 'MISSING'}")

# ============================================================
# [2] Emergence Seed Loading
# ============================================================
EMERGENCE_SEED = {}
seed_path = BASE / "emergence_seed.json"
if seed_path.exists():
    with open(seed_path, "r", encoding="utf-8") as f:
        EMERGENCE_SEED = json.load(f)
    logger.info("Emergence Seed loaded")

# ============================================================
# [3] SQLite DB Setup
# ============================================================
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS stories (
        id TEXT PRIMARY KEY,
        title TEXT,
        purpose TEXT,
        style TEXT,
        mood TEXT,
        child_name TEXT,
        child_age INTEGER,
        child_traits TEXT,
        skeleton_json TEXT,
        status TEXT DEFAULT 'pending',
        pdf_path TEXT,
        thumbnail TEXT,
        created_at REAL
    );
    CREATE TABLE IF NOT EXISTS pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        story_id TEXT,
        page_num INTEGER,
        text_ko TEXT,
        image_prompt TEXT,
        image_url TEXT,
        image_path TEXT,
        status TEXT DEFAULT 'pending',
        FOREIGN KEY(story_id) REFERENCES stories(id)
    );
    CREATE TABLE IF NOT EXISTS verifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        story_id TEXT,
        page_num INTEGER,
        score REAL,
        feedback TEXT,
        created_at REAL,
        FOREIGN KEY(story_id) REFERENCES stories(id)
    );
    """)
    conn.commit()
    conn.close()
    logger.info("DB initialized")

init_db()

# ============================================================
# [4] Styles, Moods, Beat Sheet
# ============================================================
STYLE_OPTIONS = ["수채화 동화", "파스텔 일러스트", "만화 스타일", "유화풍", "연필 스케치", "팝아트", "동양화"]
MOOD_OPTIONS = ["따뜻하고 포근한", "신비롭고 몽환적인", "밝고 유쾌한", "모험적이고 용감한", "잔잔하고 서정적인"]

BEAT_SHEET = {
    1: "평범한 일상 속 미세한 균열",
    2: "부름/발견 - 호기심의 씨앗",
    3: "문턱 넘기 - 새로운 세계 진입",
    4: "첫 번째 시련과 조력자 등장",
    5: "새로운 규칙 학습/탐험",
    6: "동맹 형성과 중간 목표 달성",
    7: "반전/배신/예상 밖의 장애물",
    8: "가장 큰 두려움과 직면",
    9: "모든 것을 잃는 순간",
    10: "내면의 발견/깨달음",
    11: "최종 결전/도전",
    12: "클라이맥스 - 성장의 증명",
    13: "새로운 균형/귀환",
    14: "변화된 일상",
    15: "여운과 열린 결말",
}

# ============================================================
# [5] LLM Utilities
# ============================================================
def strip_reasoning(text):
    if not text:
        return ""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

def safe_json_parse(text):
    text = strip_reasoning(text)
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()
    try:
        return json.loads(text)
    except:
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
        match = re.search(r'\[[\s\S]*\]', text)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    return None

def call_llm(messages, max_tokens=4096, temperature=0.7, model=None):
    if not HAS_VALID_API_KEY:
        raise Exception("Fireworks API key not configured")
    payload = {
        "model": model or FIREWORKS_LLM_MODEL,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {FIREWORKS_API_KEY}"
    }
    resp = requests.post(FIREWORKS_API_URL, headers=headers, json=payload, timeout=180)
    if resp.status_code != 200:
        raise Exception(f"LLM API error: {resp.status_code} - {resp.text[:200]}")
    return strip_reasoning(resp.json()["choices"][0]["message"]["content"])

def call_vlm(messages, max_tokens=4096, temperature=0.6):
    return call_llm(messages, max_tokens, temperature, model=FIREWORKS_VLM_MODEL)


# ============================================================
# [6] Emergence Prompt Builder
# ============================================================
def get_emergence_system(purpose, style, mood, child_name, child_age, child_traits):
    seed = EMERGENCE_SEED.get("hyper_divergent_emergence_seed", {})
    kernel = seed.get("system_kernel", {})
    circuits = seed.get("narrative_dna_circuits", {})
    operators = seed.get("emergence_operators", {})
    img_dir = seed.get("image_prompt_directives", {})

    linguistic = circuits.get("identity_matrix", {}).get("elements", {}).get("linguistic_style", {})
    forbidden_starters = linguistic.get("forbidden_sentence_starters", [])
    forbidden_cliches = linguistic.get("forbidden_cliche_expressions", [])
    emotional_map = operators.get("emotional_architecture", {}).get("emotional_beat_map", {})

    beat_emotions = ""
    for p, em in emotional_map.items():
        beat_emotions += f"  {p}: {em.get('primary','')} -> reader feels: {em.get('reader_feels','')}\n"

    return f"""당신은 세계 최고의 아동 동화 작가입니다. AXIS Narrative Engine으로 동작합니다.

## 핵심 규칙
- narrative_temperature: {kernel.get('narrative_temperature', 0.82)}
- coherence_gravity: {kernel.get('coherence_gravity', 0.91)}
- target_reread_count: {kernel.get('target_reread_count', 100)}
- dual_audience_mode: 아이와 어른 모두 감동하는 이야기

## 금지 문장 시작어: {', '.join(forbidden_starters)}
## 금지 클리셰: {', '.join(forbidden_cliches)}

## 감정 비트맵 (15페이지):
{beat_emotions}

## 이미지 구도 규칙:
{json.dumps(img_dir.get('composition_rules', []), ensure_ascii=False)}

## 캐릭터 일관성:
{json.dumps(img_dir.get('character_consistency_anchors', []), ensure_ascii=False)}

## 동화 설정:
- 목적/주제: {purpose}
- 화풍: {style}
- 분위기: {mood}
- 주인공 이름: {child_name}
- 주인공 나이: {child_age}세
- 주인공 특징: {child_traits}

모든 출력은 한국어로 작성하세요."""

# ============================================================
# [7] Story Generation Pipeline
# ============================================================
story_progress: Dict[str, Dict[str, Any]] = {}

def update_progress(story_id, step, page=0, total=15, detail=""):
    pct_map = {"skeleton": 5, "text": 10 + int(page/total*40), "image": 50 + int(page/total*40), "verify": 92, "pdf": 96, "done": 100, "error": -1}
    story_progress[story_id] = {
        "step": step, "page": page, "total": total,
        "progress": pct_map.get(step, 0), "detail": detail,
        "status": "error" if step == "error" else ("completed" if step == "done" else "generating")
    }

def step1_create_skeleton(story_id, purpose, style, mood, child_name, child_age, child_traits):
    update_progress(story_id, "skeleton", detail="스켈레톤 생성 중...")
    system = get_emergence_system(purpose, style, mood, child_name, child_age, child_traits)
    beat_list = "\n".join([f"P{k}: {v}" for k, v in BEAT_SHEET.items()])
    prompt = f"""다음 15페이지 비트시트에 맞는 동화 스켈레톤을 JSON으로 생성하세요:

{beat_list}

JSON 형식:
{{
  "title": "동화 제목",
  "theme": "핵심 테마",
  "protagonist": {{
    "name": "{child_name}",
    "age": {child_age},
    "traits": "{child_traits}",
    "flaw": "성장할 결점",
    "external_goal": "외적 목표",
    "internal_need": "내적 필요"
  }},
  "ally": {{"name": "이름", "species": "종류", "trait": "특징", "role": "역할"}},
  "antagonist": {{"name": "이름", "type": "유형", "motivation": "동기"}},
  "foreshadowing_seeds": ["복선1", "복선2", "복선3"],
  "signature_line": "반복되는 핵심 대사",
  "world_setting": "세계관 설명",
  "magic_rules": "마법 규칙 (있다면)"
}}"""

    result = call_llm([{"role": "system", "content": system}, {"role": "user", "content": prompt}], max_tokens=4096, temperature=0.8)
    skeleton = safe_json_parse(result)
    if not skeleton:
        raise Exception("Failed to parse skeleton JSON")

    conn = get_db()
    conn.execute("UPDATE stories SET skeleton_json=?, title=?, status='skeleton_done' WHERE id=?",
                 (json.dumps(skeleton, ensure_ascii=False), skeleton.get("title", "무제"), story_id))
    conn.commit()
    conn.close()
    return skeleton

def step2_generate_page_text(story_id, skeleton, purpose, style, mood, child_name, child_age, child_traits):
    system = get_emergence_system(purpose, style, mood, child_name, child_age, child_traits)
    conn = get_db()

    for page_num in range(1, 16):
        update_progress(story_id, "text", page=page_num, detail=f"페이지 {page_num}/15 텍스트 생성 중...")
        beat = BEAT_SHEET.get(page_num, "")
        prompt = f"""동화 "{skeleton.get('title','')}" 의 페이지 {page_num}/15를 작성하세요.

스켈레톤: {json.dumps(skeleton, ensure_ascii=False)}

이 페이지의 비트: {beat}

JSON으로 응답:
{{
  "page_num": {page_num},
  "text_ko": "이 페이지의 본문 (4~6문장, 아이가 읽기 좋은 길이)",
  "image_prompt": "이 페이지의 삽화를 위한 영어 프롬프트 (상세하고 구체적)"
}}"""

        result = call_llm([{"role": "system", "content": system}, {"role": "user", "content": prompt}], max_tokens=2048, temperature=0.75)
        parsed = safe_json_parse(result)
        if parsed:
            conn.execute("INSERT INTO pages (story_id, page_num, text_ko, image_prompt, status) VALUES (?,?,?,?,?)",
                         (story_id, page_num, parsed.get("text_ko", ""), parsed.get("image_prompt", ""), "text_done"))
        else:
            conn.execute("INSERT INTO pages (story_id, page_num, text_ko, image_prompt, status) VALUES (?,?,?,?,?)",
                         (story_id, page_num, result[:500], "", "text_fallback"))
        conn.commit()
        time.sleep(1)

    conn.execute("UPDATE stories SET status='text_done' WHERE id=?", (story_id,))
    conn.commit()
    conn.close()

def step3_generate_images(story_id, style):
    conn = get_db()
    pages = conn.execute("SELECT * FROM pages WHERE story_id=? ORDER BY page_num", (story_id,)).fetchall()

    story_img_dir = STORIES_DIR / story_id / "images"
    story_img_dir.mkdir(parents=True, exist_ok=True)

    for page in pages:
        page_num = page["page_num"]
        update_progress(story_id, "image", page=page_num, detail=f"페이지 {page_num}/15 삽화 생성 중...")
        image_prompt = page["image_prompt"]
        if not image_prompt:
            continue

        full_prompt = f"{style} style children's book illustration. {image_prompt}. High quality, vibrant colors, child-friendly, professional illustration."

        image_url = None
        image_path = None

        if HAS_FAL_KEY:
            try:
                import fal_client
                result = fal_client.subscribe("xai/grok-imagine-image", arguments={"prompt": full_prompt})
                if result and result.get("images"):
                    image_url = result["images"][0].get("url", "")
                    if image_url:
                        img_resp = requests.get(image_url, timeout=60)
                        if img_resp.status_code == 200:
                            img_path = story_img_dir / f"page_{page_num:02d}.png"
                            img_path.write_bytes(img_resp.content)
                            image_path = str(img_path)
            except Exception as e:
                logger.error(f"Image gen error page {page_num}: {e}")

        conn.execute("UPDATE pages SET image_url=?, image_path=?, status='image_done' WHERE story_id=? AND page_num=?",
                     (image_url or "", image_path or "", story_id, page_num))
        conn.commit()
        time.sleep(2)

    conn.execute("UPDATE stories SET status='images_done' WHERE id=?", (story_id,))
    conn.commit()
    conn.close()

def step4_verify(story_id):
    update_progress(story_id, "verify", detail="품질 검증 중...")
    conn = get_db()
    pages = conn.execute("SELECT * FROM pages WHERE story_id=? ORDER BY page_num", (story_id,)).fetchall()
    story = conn.execute("SELECT * FROM stories WHERE id=?", (story_id,)).fetchone()

    all_text = "\n\n".join([f"[P{p['page_num']}] {p['text_ko']}" for p in pages])
    prompt = f"""다음 15페이지 동화의 품질을 검증하세요. 100점 만점으로 평가하고 피드백을 주세요.

제목: {story['title']}
전체 텍스트:
{all_text[:6000]}

JSON으로 응답:
{{"overall_score": 85, "feedback": "전반적 피드백", "page_scores": [{{"page": 1, "score": 90, "note": "코멘트"}}]}}"""

    try:
        result = call_llm([{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.3)
        parsed = safe_json_parse(result)
        if parsed:
            score = parsed.get("overall_score", 75)
            conn.execute("INSERT INTO verifications (story_id, page_num, score, feedback, created_at) VALUES (?,?,?,?,?)",
                         (story_id, 0, score, json.dumps(parsed, ensure_ascii=False), time.time()))
            conn.commit()
    except Exception as e:
        logger.error(f"Verification error: {e}")

    conn.execute("UPDATE stories SET status='verified' WHERE id=?", (story_id,))
    conn.commit()
    conn.close()


# ============================================================
# [8] PDF Generation (ReportLab)
# ============================================================
def generate_pdf(story_id):
    update_progress(story_id, "pdf", detail="PDF 생성 중...")
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    import io

    conn = get_db()
    story = conn.execute("SELECT * FROM stories WHERE id=?", (story_id,)).fetchone()
    pages = conn.execute("SELECT * FROM pages WHERE story_id=? ORDER BY page_num", (story_id,)).fetchall()

    pdf_dir = STORIES_DIR / story_id
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / f"{story_id}.pdf"

    page_w, page_h = 210*mm, 210*mm
    c = canvas.Canvas(str(pdf_path), pagesize=(page_w, page_h))

    # Try to register Korean font
    font_name = "Helvetica"
    font_paths = ["/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont("KoreanFont", fp))
                font_name = "KoreanFont"
                break
            except:
                pass

    # Cover page
    c.setFont(font_name, 28)
    title = story["title"] or "My Story"
    c.drawCentredString(page_w/2, page_h*0.6, title)
    c.setFont(font_name, 16)
    c.drawCentredString(page_w/2, page_h*0.45, f"by {story['child_name'] or 'Author'}")
    c.showPage()

    # Content pages
    for page in pages:
        # Draw image if exists
        img_path = page["image_path"]
        if img_path and os.path.exists(img_path):
            try:
                img = Image.open(img_path)
                img_w, img_h = img.size
                aspect = img_w / img_h
                draw_w = page_w - 20*mm
                draw_h = draw_w / aspect
                if draw_h > page_h * 0.6:
                    draw_h = page_h * 0.6
                    draw_w = draw_h * aspect
                x = (page_w - draw_w) / 2
                y = page_h - draw_h - 10*mm
                c.drawImage(ImageReader(img), x, y, draw_w, draw_h)
            except Exception as e:
                logger.error(f"PDF image error: {e}")

        # Draw text
        text_ko = page["text_ko"] or ""
        c.setFont(font_name, 11)
        text_y = page_h * 0.3
        for line in text_ko.split("\n"):
            words = line
            while len(words) > 35:
                c.drawCentredString(page_w/2, text_y, words[:35])
                words = words[35:]
                text_y -= 16
            c.drawCentredString(page_w/2, text_y, words)
            text_y -= 16

        # Page number
        c.setFont(font_name, 9)
        c.drawCentredString(page_w/2, 8*mm, f"- {page['page_num']} -")
        c.showPage()

    c.save()

    conn.execute("UPDATE stories SET pdf_path=?, status='pdf_done' WHERE id=?", (str(pdf_path), story_id))
    conn.commit()
    conn.close()
    return str(pdf_path)

# ============================================================
# [9] PDF to Page Images (for FlipBook)
# ============================================================
def pdf_to_flipbook_pages(pdf_path, scale=1.0, quality=80):
    pages = []
    try:
        doc = fitz.open(pdf_path)
        for i in range(doc.page_count):
            page = doc[i]
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            img_data = pix.tobytes("jpeg", quality)
            b64 = base64.b64encode(img_data).decode()
            pages.append({"src": f"data:image/jpeg;base64,{b64}", "thumb": ""})
        doc.close()
    except Exception as e:
        logger.error(f"PDF to flipbook error: {e}")
    return pages

def get_story_thumbnail(story_id):
    conn = get_db()
    story = conn.execute("SELECT pdf_path, thumbnail FROM stories WHERE id=?", (story_id,)).fetchone()
    if not story:
        return None
    if story["thumbnail"]:
        return story["thumbnail"]
    pdf_path = story["pdf_path"]
    if not pdf_path or not os.path.exists(pdf_path):
        return None
    try:
        doc = fitz.open(pdf_path)
        if doc.page_count > 0:
            page = doc[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(0.3, 0.3))
            img_data = pix.tobytes("jpeg", 70)
            thumb = f"data:image/jpeg;base64,{base64.b64encode(img_data).decode()}"
            doc.close()
            conn2 = get_db()
            conn2.execute("UPDATE stories SET thumbnail=? WHERE id=?", (thumb, story_id))
            conn2.commit()
            conn2.close()
            return thumb
        doc.close()
    except:
        pass
    return None

# ============================================================
# [10] Full Pipeline Runner
# ============================================================
def run_full_pipeline(story_id, purpose, style, mood, child_name, child_age, child_traits):
    try:
        skeleton = step1_create_skeleton(story_id, purpose, style, mood, child_name, child_age, child_traits)
        step2_generate_page_text(story_id, skeleton, purpose, style, mood, child_name, child_age, child_traits)
        step3_generate_images(story_id, style)
        step4_verify(story_id)
        generate_pdf(story_id)
        update_progress(story_id, "done", detail="완료!")
        logger.info(f"Story {story_id} pipeline completed")
    except Exception as e:
        logger.error(f"Pipeline error for {story_id}: {e}")
        update_progress(story_id, "error", detail=str(e))
        conn = get_db()
        conn.execute("UPDATE stories SET status='error' WHERE id=?", (story_id,))
        conn.commit()
        conn.close()

# ============================================================
# [11] Existing PDF Caching (from 3d-kid)
# ============================================================
PROMPT_PDF_PATH = BASE / "prompt.pdf"
PDF_FILES = {
    "prompt": {"path": BASE / "prompt.pdf", "id": "prompt_pdf_main", "name": "샘플-프롬프트북"},
    "ktx": {"path": BASE / "ktx2512.pdf", "id": "ktx_pdf_main", "name": "샘플-코레일잡지"},
}
current_pdf_key = "prompt"
pdf_cache: Dict[str, Dict[str, Any]] = {}
cache_locks = {}
pdf_embeddings: Dict[str, Dict[str, Any]] = {}
analysis_status: Dict[str, Dict[str, Any]] = {}

def get_cache_path(pdf_name): return CACHE_DIR / f"{pdf_name}_cache.json"
def get_analysis_cache_path(pdf_id): return EMBEDDING_DIR / f"{pdf_id}_vlm_analysis.json"

def load_analysis_cache(pdf_id):
    p = get_analysis_cache_path(pdf_id)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return None

def save_analysis_cache(pdf_id, data):
    try:
        with open(get_analysis_cache_path(pdf_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Save analysis cache error: {e}")

def get_pdf_page_as_base64(pdf_path, page_num, scale=1.0):
    try:
        doc = fitz.open(pdf_path)
        if page_num >= doc.page_count:
            doc.close()
            return None
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        img_data = pix.tobytes("jpeg", 85)
        b64 = base64.b64encode(img_data).decode()
        doc.close()
        return b64
    except:
        return None

def get_pdf_pages_as_base64(pdf_path, start_page=0, max_pages=10, scale=0.7):
    try:
        doc = fitz.open(pdf_path)
        total = doc.page_count
        end = min(start_page + max_pages, total)
        images = []
        for pn in range(start_page, end):
            page = doc[pn]
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            img_data = pix.tobytes("jpeg", 75)
            images.append({"page": pn+1, "image_base64": base64.b64encode(img_data).decode()})
        doc.close()
        return images, total
    except:
        return [], 0

async def cache_pdf(pdf_path_str):
    try:
        pdf_file = pathlib.Path(pdf_path_str)
        pdf_name = pdf_file.stem
        if pdf_name not in cache_locks:
            cache_locks[pdf_name] = threading.Lock()
        if pdf_name in pdf_cache and pdf_cache[pdf_name].get("status") in ["processing", "completed"]:
            return
        with cache_locks[pdf_name]:
            if pdf_name in pdf_cache and pdf_cache[pdf_name].get("status") in ["processing", "completed"]:
                return
            pdf_cache[pdf_name] = {"status": "processing", "progress": 0, "pages": []}
            cp = get_cache_path(pdf_name)
            if cp.exists():
                try:
                    with open(cp) as f:
                        cached = json.load(f)
                    if cached.get("status") == "completed" and cached.get("pages"):
                        pdf_cache[pdf_name] = cached
                        return
                except:
                    pass
            doc = fitz.open(pdf_path_str)
            total = doc.page_count
            pages_list = [None] * total
            sf, jq = 1.0, 80
            def proc(pn):
                try:
                    pg = doc[pn]
                    pix = pg.get_pixmap(matrix=fitz.Matrix(sf, sf))
                    d = pix.tobytes("jpeg", jq)
                    return {"page_num": pn, "src": f"data:image/jpeg;base64,{base64.b64encode(d).decode()}", "thumb": ""}
                except:
                    return {"page_num": pn, "src": "", "thumb": ""}
            cnt = 0
            for bs in range(0, total, 5):
                be = min(bs+5, total)
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                    results = list(ex.map(proc, range(bs, be)))
                for r in results:
                    pages_list[r["page_num"]] = {"src": r["src"], "thumb": r["thumb"]}
                    cnt += 1
                    pdf_cache[pdf_name]["progress"] = round(cnt/total*100)
                pdf_cache[pdf_name]["pages"] = pages_list
            pdf_cache[pdf_name] = {"status": "completed", "progress": 100, "pages": pages_list, "total_pages": total}
            try:
                with open(cp, "w") as f:
                    json.dump(pdf_cache[pdf_name], f)
            except:
                pass
    except Exception as e:
        logger.error(f"PDF cache error: {e}")

# ============================================================
# [12] VLM Analysis (existing)
# ============================================================
def analyze_batch_pages_sync(pdf_path, start_page, batch_size=5):
    imgs, total = get_pdf_pages_as_base64(pdf_path, start_page, batch_size, scale=0.6)
    if not imgs:
        return ""
    parts = []
    for img in imgs:
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img['image_base64']}"}})
    rng = f"{start_page+1}~{start_page+len(imgs)}"
    parts.append({"type": "text", "text": f"위 이미지들은 PDF {rng}페이지입니다. 각 페이지 내용을 상세 분석하여 한국어로 작성해주세요."})
    return call_vlm([{"role": "user", "content": parts}], max_tokens=4096, temperature=0.3)

async def analyze_pdf_with_vlm(pdf_id, pdf_path_str, force=False):
    global analysis_status
    if pdf_id in analysis_status and analysis_status[pdf_id].get("status") == "analyzing":
        return {"status": "analyzing"}
    if not force:
        cached = load_analysis_cache(pdf_id)
        if cached:
            analysis_status[pdf_id] = {"status": "completed", "progress": 100}
            return cached
    if not HAS_VALID_API_KEY:
        return {"error": "API key missing"}
    analysis_status[pdf_id] = {"status": "analyzing", "progress": 0}
    try:
        doc = fitz.open(pdf_path_str)
        total = doc.page_count
        doc.close()
        all_a = []
        for sp in range(0, min(total, 25), 5):
            analysis_status[pdf_id]["progress"] = int(sp/min(total,25)*100)
            loop = asyncio.get_event_loop()
            br = await loop.run_in_executor(None, analyze_batch_pages_sync, pdf_path_str, sp, 5)
            if br:
                all_a.append(f"### P{sp+1}~{min(sp+5,total)}\n{br}")
            await asyncio.sleep(2)
        combined = "\n\n".join(all_a)
        summary = combined[:500] + "..."
        if combined:
            try:
                summary = call_llm([{"role": "system", "content": "500자 이내로 요약해주세요."}, {"role": "user", "content": combined[:8000]}], max_tokens=1024, temperature=0.5)
            except:
                pass
        data = {"pdf_id": pdf_id, "total_pages": total, "analyzed_pages": min(total,25), "analysis": combined, "summary": summary, "created_at": time.time()}
        save_analysis_cache(pdf_id, data)
        analysis_status[pdf_id] = {"status": "completed", "progress": 100}
        return data
    except Exception as e:
        analysis_status[pdf_id] = {"status": "error", "error": str(e)}
        return {"error": str(e)}

async def query_pdf(pdf_id, query):
    if not HAS_VALID_API_KEY:
        return {"answer": "API 키가 없어 답변할 수 없습니다."}
    cached = load_analysis_cache(pdf_id)
    if not cached:
        return {"answer": "PDF 분석이 완료되지 않았습니다."}
    analysis_text = cached.get("analysis", "")
    msgs = [
        {"role": "system", "content": f"PDF 분석 결과를 기반으로 질문에 한국어로 답변하세요.\n\n=== 분석 ===\n{analysis_text[:12000]}"},
        {"role": "user", "content": query}
    ]
    try:
        answer = call_vlm(msgs, max_tokens=4096, temperature=0.6)
        return {"answer": answer, "pdf_id": pdf_id}
    except Exception as e:
        return {"answer": f"오류: {e}"}


# ============================================================
# [13] FastAPI Endpoints
# ============================================================

@app.on_event("startup")
async def startup_event():
    global current_pdf_key
    current_pdf_key = "prompt"
    for key, info in PDF_FILES.items():
        if info["path"].exists():
            asyncio.create_task(cache_pdf(str(info["path"])))
            if key == "prompt":
                asyncio.create_task(analyze_pdf_with_vlm(info["id"], str(info["path"])))

# --- Existing PDF endpoints ---
@app.get("/api/pdf-list")
async def get_pdf_list():
    return {"pdfs": [{"key": k, "name": v["name"], "exists": v["path"].exists(), "is_current": k == current_pdf_key} for k, v in PDF_FILES.items()], "current": current_pdf_key}

@app.post("/api/switch-pdf/{pdf_key}")
async def switch_pdf(pdf_key: str, bg: BackgroundTasks):
    global current_pdf_key
    if pdf_key not in PDF_FILES:
        return JSONResponse(content={"error": "Invalid PDF key"}, status_code=400)
    info = PDF_FILES[pdf_key]
    if not info["path"].exists():
        return JSONResponse(content={"error": "PDF not found"}, status_code=404)
    current_pdf_key = pdf_key
    pn = info["path"].stem
    if pn not in pdf_cache or pdf_cache[pn].get("status") != "completed":
        bg.add_task(cache_pdf, str(info["path"]))
    if not load_analysis_cache(info["id"]):
        asyncio.create_task(analyze_pdf_with_vlm(info["id"], str(info["path"])))
    return {"success": True, "current": pdf_key, "name": info["name"]}

@app.get("/api/pdf-info")
async def get_pdf_info():
    info = PDF_FILES.get(current_pdf_key, PDF_FILES["prompt"])
    pn = info["path"].stem
    return {"path": str(info["path"]), "name": pn, "display_name": info["name"], "id": info["id"], "key": current_pdf_key, "exists": info["path"].exists(), "cached": pn in pdf_cache and pdf_cache[pn].get("status") == "completed", "analysis_cached": load_analysis_cache(info["id"]) is not None}

@app.get("/api/analysis-status")
async def get_analysis_status_ep():
    info = PDF_FILES.get(current_pdf_key, PDF_FILES["prompt"])
    pid = info["id"]
    cached = load_analysis_cache(pid)
    if cached:
        return {"status": "completed", "total_pages": cached.get("total_pages", 0), "analyzed_pages": cached.get("analyzed_pages", 0)}
    if pid in analysis_status:
        return analysis_status[pid]
    return {"status": "not_started"}

@app.get("/api/cache-status")
async def get_cache_status():
    pn = PDF_FILES.get(current_pdf_key, PDF_FILES["prompt"])["path"].stem
    return pdf_cache.get(pn, {"status": "not_cached"})

@app.get("/api/cached-pdf")
async def get_cached_pdf(bg: BackgroundTasks):
    info = PDF_FILES.get(current_pdf_key, PDF_FILES["prompt"])
    pn = info["path"].stem
    if pn in pdf_cache:
        s = pdf_cache[pn].get("status", "")
        if s == "completed":
            return pdf_cache[pn]
        elif s == "processing":
            return {"status": "processing", "progress": pdf_cache[pn].get("progress", 0), "pages": pdf_cache[pn].get("pages", []), "total_pages": pdf_cache[pn].get("total_pages", 0)}
    if info["path"].exists():
        bg.add_task(cache_pdf, str(info["path"]))
    return {"status": "started", "progress": 0}

@app.get("/api/pdf-thumbnail")
async def get_pdf_thumbnail():
    info = PDF_FILES.get(current_pdf_key, PDF_FILES["prompt"])
    if not info["path"].exists():
        return {"thumbnail": None}
    pn = info["path"].stem
    if pn in pdf_cache and pdf_cache[pn].get("pages"):
        if pdf_cache[pn]["pages"][0] and pdf_cache[pn]["pages"][0].get("thumb"):
            return {"thumbnail": pdf_cache[pn]["pages"][0]["thumb"]}
    try:
        doc = fitz.open(str(info["path"]))
        if doc.page_count > 0:
            pg = doc[0]
            pix = pg.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
            d = pix.tobytes("jpeg", 70)
            doc.close()
            return {"thumbnail": f"data:image/jpeg;base64,{base64.b64encode(d).decode()}"}
    except:
        pass
    return {"thumbnail": None}

@app.post("/api/ai/query-pdf")
async def api_query_pdf(body: Dict[str, str]):
    q = body.get("query", "")
    if not q:
        return JSONResponse(content={"error": "No query"}, status_code=400)
    info = PDF_FILES.get(current_pdf_key, PDF_FILES["prompt"])
    result = await query_pdf(info["id"], q)
    return result

@app.get("/api/ai/summarize-pdf")
async def api_summarize_pdf():
    info = PDF_FILES.get(current_pdf_key, PDF_FILES["prompt"])
    cached = load_analysis_cache(info["id"])
    if cached and cached.get("summary"):
        return {"summary": cached["summary"], "total_pages": cached.get("total_pages", 0), "analyzed_pages": cached.get("analyzed_pages", 0)}
    return {"summary": "분석이 완료되지 않았습니다."}

@app.post("/api/reanalyze-pdf")
async def reanalyze_pdf():
    info = PDF_FILES.get(current_pdf_key, PDF_FILES["prompt"])
    pid = info["id"]
    cp = get_analysis_cache_path(pid)
    if cp.exists():
        cp.unlink()
    if pid in analysis_status:
        del analysis_status[pid]
    asyncio.create_task(analyze_pdf_with_vlm(pid, str(info["path"]), force=True))
    return {"status": "started"}

# --- New Story endpoints ---
@app.post("/api/story/create")
async def create_story(body: Dict[str, Any], bg: BackgroundTasks):
    story_id = uuid.uuid4().hex[:12]
    purpose = body.get("purpose", "")
    style = body.get("style", "수채화 동화")
    mood = body.get("mood", "따뜻하고 포근한")
    child_name = body.get("child_name", "주인공")
    child_age = body.get("child_age", 6)
    child_traits = body.get("child_traits", "")

    if not purpose:
        return JSONResponse(content={"error": "동화 주제를 입력해주세요"}, status_code=400)
    if not HAS_VALID_API_KEY:
        return JSONResponse(content={"error": "API 키가 설정되지 않았습니다"}, status_code=400)

    conn = get_db()
    conn.execute("INSERT INTO stories (id, purpose, style, mood, child_name, child_age, child_traits, status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (story_id, purpose, style, mood, child_name, child_age, child_traits, "started", time.time()))
    conn.commit()
    conn.close()

    update_progress(story_id, "skeleton", detail="시작...")
    bg.add_task(run_full_pipeline, story_id, purpose, style, mood, child_name, child_age, child_traits)
    return {"story_id": story_id, "status": "started"}

@app.get("/api/story/status/{story_id}")
async def get_story_status(story_id: str):
    if story_id in story_progress:
        return story_progress[story_id]
    conn = get_db()
    story = conn.execute("SELECT status FROM stories WHERE id=?", (story_id,)).fetchone()
    conn.close()
    if story:
        return {"status": story["status"], "progress": 100 if story["status"] in ("pdf_done", "verified") else 50}
    return {"status": "not_found"}

@app.get("/api/story/list")
async def list_stories():
    conn = get_db()
    rows = conn.execute("SELECT id, title, purpose, style, mood, child_name, status, pdf_path, thumbnail, created_at FROM stories ORDER BY created_at DESC LIMIT 50").fetchall()
    conn.close()
    stories = []
    for r in rows:
        thumb = r["thumbnail"]
        if not thumb and r["pdf_path"] and os.path.exists(r["pdf_path"] or ""):
            thumb = get_story_thumbnail(r["id"])
        stories.append({
            "story_id": r["id"], "title": r["title"] or r["purpose"][:30], "purpose": r["purpose"],
            "style": r["style"], "mood": r["mood"], "child_name": r["child_name"],
            "status": r["status"], "has_pdf": bool(r["pdf_path"] and os.path.exists(r["pdf_path"] or "")),
            "thumbnail": thumb, "created_at": r["created_at"]
        })
    return {"stories": stories}

@app.get("/api/story/{story_id}/flipbook")
async def get_story_flipbook(story_id: str):
    conn = get_db()
    story = conn.execute("SELECT pdf_path FROM stories WHERE id=?", (story_id,)).fetchone()
    conn.close()
    if not story or not story["pdf_path"] or not os.path.exists(story["pdf_path"]):
        return JSONResponse(content={"error": "PDF not found"}, status_code=404)
    pages = pdf_to_flipbook_pages(story["pdf_path"])
    return {"status": "completed", "pages": pages, "total_pages": len(pages)}

@app.get("/api/story/{story_id}/pdf")
async def download_story_pdf(story_id: str):
    conn = get_db()
    story = conn.execute("SELECT pdf_path, title FROM stories WHERE id=?", (story_id,)).fetchone()
    conn.close()
    if not story or not story["pdf_path"] or not os.path.exists(story["pdf_path"]):
        return JSONResponse(content={"error": "PDF not found"}, status_code=404)
    fname = f"{story['title'] or 'story'}.pdf"
    return FileResponse(story["pdf_path"], media_type="application/pdf", filename=fname)


# ============================================================
# [14] Main HTML Page
# ============================================================
@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(content=HTML_CONTENT)

HTML_CONTENT = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI BOOK MAKER - 3D FlipBook</title>
  <link href="https://fonts.googleapis.com/css2?family=Bangers&family=Comic+Neue:wght@400;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <link rel="stylesheet" href="/static/flipbook.css">
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <script src="/static/three.js"></script>
  <script src="/static/pdf.js"></script>
  <script src="/static/iscroll.js"></script>
  <script src="/static/mark.js"></script>
  <script src="/static/mod3d.js"></script>
  <script src="/static/flipbook.js"></script>
  <script src="/static/flipbook.book3.js"></script>
  <script src="/static/flipbook.webgl.js"></script>
  <script src="/static/flipbook.scroll.js"></script>
  <script src="/static/flipbook.swipe.js"></script>
  <style>
  :root {
    --primary: #3B82F6; --secondary: #8B5CF6; --accent: #FACC15;
    --danger: #EF4444; --success: #10B981; --dark: #1F2937;
    --card-bg: #FFF; --bg-warm: #FEF9C3;
    --shadow: 4px 4px 0 #1F2937; --radius: 12px;
    --transition: all 0.3s ease;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: linear-gradient(135deg, #FEF9C3 0%, #FECACA 50%, #E0E7FF 100%); min-height: 100vh; overflow-x: hidden; }

  .header-info { position: fixed; top: 12px; left: 50%; transform: translateX(-50%); z-index: 5000;
    background: linear-gradient(135deg, var(--danger) 0%, #F97316 100%); padding: 8px 24px;
    border: 3px solid var(--dark); border-radius: 25px; box-shadow: var(--shadow); }
  .header-info .title { font-family: 'Bangers', cursive; font-size: 1.3rem; color: #FFF; letter-spacing: 2px; text-shadow: 2px 2px 0 var(--dark); }

  /* Floating Buttons */
  .floating-btn { position: fixed; z-index: 5000; width: 50px; height: 50px; border-radius: 50%;
    border: 3px solid var(--dark); display: flex; align-items: center; justify-content: center;
    cursor: pointer; box-shadow: var(--shadow); transition: var(--transition); }
  .floating-btn:hover { transform: translate(-2px,-2px); box-shadow: 6px 6px 0 var(--dark); }
  .floating-btn .icon { font-size: 20px; color: #FFF; }

  .floating-ai { top: 12px; right: 16px; background: linear-gradient(135deg, var(--success), #059669); }
  .floating-create { top: 12px; left: 16px; background: linear-gradient(135deg, var(--secondary), #7C3AED); }
  .floating-pdf-btn { right: 16px; width: 45px; height: 45px; }
  .floating-pdf-btn.active { border-color: var(--accent); box-shadow: 0 0 12px var(--accent); }
  #pdfPromptBtn { top: 70px; background: linear-gradient(135deg, var(--primary), #2563EB); }
  #pdfKtxBtn { top: 122px; background: linear-gradient(135deg, #F97316, #EA580C); }

  /* Viewer */
  #viewer { width: 94%; height: 90vh; max-width: 94%; margin: 0; background: var(--card-bg);
    border: 4px solid var(--dark); border-radius: var(--radius); position: fixed;
    top: 50%; left: 50%; transform: translate(-50%, -50%); z-index: 1000;
    box-shadow: 8px 8px 0 var(--dark); overflow: hidden; display: none; }

  /* Gallery View */
  #galleryView { position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 500;
    overflow-y: auto; padding: 80px 20px 100px; }
  .gallery-title { font-family: 'Bangers', cursive; font-size: 2rem; color: var(--dark);
    text-align: center; margin-bottom: 30px; letter-spacing: 3px; text-shadow: 2px 2px 0 var(--accent); }
  .gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 20px; max-width: 1200px; margin: 0 auto; }

  .story-card { background: #FFF; border: 3px solid var(--dark); border-radius: var(--radius);
    overflow: hidden; cursor: pointer; box-shadow: var(--shadow); transition: var(--transition); }
  .story-card:hover { transform: translate(-3px,-3px); box-shadow: 7px 7px 0 var(--dark); }
  .story-card .card-img { width: 100%; height: 180px; object-fit: cover; border-bottom: 3px solid var(--dark); background: var(--bg-warm); display: flex; align-items: center; justify-content: center; }
  .story-card .card-img img { width: 100%; height: 100%; object-fit: cover; }
  .story-card .card-img .placeholder { font-size: 3rem; }
  .story-card .card-body { padding: 12px; }
  .story-card .card-title { font-family: 'Bangers', cursive; font-size: 1.1rem; color: var(--dark); margin-bottom: 4px; }
  .story-card .card-meta { font-family: 'Comic Neue', cursive; font-size: 0.8rem; color: #6B7280; }
  .story-card .card-actions { display: flex; gap: 8px; margin-top: 8px; }
  .story-card .card-btn { flex: 1; padding: 6px; border: 2px solid var(--dark); border-radius: 8px;
    font-family: 'Comic Neue', cursive; font-weight: 700; font-size: 0.75rem; cursor: pointer;
    text-align: center; box-shadow: 2px 2px 0 var(--dark); transition: var(--transition); }
  .card-btn.view { background: var(--primary); color: #FFF; }
  .card-btn.download { background: var(--success); color: #FFF; }
  .card-btn.generating { background: #9CA3AF; color: #FFF; cursor: wait; }

  .create-card { background: linear-gradient(135deg, var(--secondary), #7C3AED); border: 3px dashed var(--dark);
    display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 260px; }
  .create-card .icon { font-size: 3rem; color: #FFF; margin-bottom: 10px; }
  .create-card .label { font-family: 'Bangers', cursive; font-size: 1.3rem; color: #FFF; letter-spacing: 2px; }

  /* Create Panel (Left slide) */
  #createPanel { position: fixed; top: 0; left: 0; width: 420px; height: 100%; background: #FFF;
    border-right: 4px solid var(--dark); box-shadow: 8px 0 0 rgba(0,0,0,0.1); z-index: 10000;
    transform: translateX(-100%); transition: transform 0.3s ease; display: flex; flex-direction: column; overflow-y: auto; }
  #createPanel.active { transform: translateX(0); }
  .panel-header { display: flex; justify-content: space-between; align-items: center; padding: 20px;
    background: linear-gradient(135deg, var(--secondary), #7C3AED); border-bottom: 4px solid var(--dark); }
  .panel-header h3 { color: #FFF; font-family: 'Bangers', cursive; font-size: 1.5rem; letter-spacing: 2px; text-shadow: 2px 2px 0 var(--dark); }
  .panel-close { width: 40px; height: 40px; background: #FFF; border: 3px solid var(--dark);
    border-radius: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center;
    box-shadow: 3px 3px 0 var(--dark); font-size: 18px; }
  .panel-body { padding: 20px; flex: 1; }
  .form-group { margin-bottom: 16px; }
  .form-label { font-family: 'Comic Neue', cursive; font-weight: 700; color: var(--dark); margin-bottom: 6px; display: block; font-size: 0.9rem; }
  .form-input, .form-select, .form-textarea { width: 100%; padding: 10px 14px; border: 3px solid var(--dark);
    border-radius: 8px; font-family: 'Comic Neue', cursive; font-weight: 700; font-size: 0.9rem;
    background: var(--bg-warm); transition: var(--transition); }
  .form-input:focus, .form-select:focus, .form-textarea:focus { border-color: var(--primary); box-shadow: 3px 3px 0 var(--primary); outline: none; }
  .form-textarea { min-height: 80px; resize: vertical; }
  .form-row { display: flex; gap: 12px; }
  .form-row .form-group { flex: 1; }

  .submit-btn { width: 100%; padding: 14px; background: linear-gradient(135deg, var(--danger), #F97316);
    border: 3px solid var(--dark); border-radius: 12px; color: #FFF; font-family: 'Bangers', cursive;
    font-size: 1.3rem; letter-spacing: 2px; cursor: pointer; box-shadow: var(--shadow); transition: var(--transition); }
  .submit-btn:hover { transform: translate(-2px,-2px); box-shadow: 6px 6px 0 var(--dark); }
  .submit-btn:disabled { background: #9CA3AF; cursor: not-allowed; transform: none; }

  /* Progress */
  .progress-section { margin-top: 20px; padding: 16px; background: var(--bg-warm); border: 3px solid var(--dark); border-radius: var(--radius); display: none; }
  .progress-section.active { display: block; }
  .progress-title { font-family: 'Bangers', cursive; font-size: 1.1rem; color: var(--dark); margin-bottom: 8px; }
  .progress-bar-wrap { width: 100%; height: 20px; background: #E5E7EB; border: 2px solid var(--dark); border-radius: 10px; overflow: hidden; }
  .progress-bar-fill { height: 100%; background: linear-gradient(to right, var(--primary), var(--secondary)); border-radius: 8px; transition: width 0.5s ease; }
  .progress-detail { font-family: 'Comic Neue', cursive; font-size: 0.85rem; color: #6B7280; margin-top: 6px; font-weight: 700; }

  /* AI Chat (Right slide) */
  #aiChatContainer { position: fixed; top: 0; right: 0; width: 420px; height: 100%; background: #FFF;
    border-left: 4px solid var(--dark); z-index: 10000; transform: translateX(100%);
    transition: transform 0.3s ease; display: flex; flex-direction: column; }
  #aiChatContainer.active { transform: translateX(0); }
  #aiChatHeader { display: flex; justify-content: space-between; align-items: center; padding: 20px;
    border-bottom: 4px solid var(--dark); background: linear-gradient(135deg, var(--danger), #F97316); }
  #aiChatHeader h3 { margin: 0; color: #FFF; font-family: 'Bangers', cursive; font-size: 1.5rem;
    letter-spacing: 2px; text-shadow: 2px 2px 0 var(--dark); }
  #aiChatMessages { flex: 1; overflow-y: auto; padding: 20px; background: var(--bg-warm); }
  .chat-message { margin-bottom: 15px; display: flex; align-items: flex-start; }
  .chat-message.user { flex-direction: row-reverse; }
  .chat-avatar { width: 36px; height: 36px; border-radius: 8px; border: 3px solid var(--dark);
    display: flex; justify-content: center; align-items: center; flex-shrink: 0; box-shadow: 2px 2px 0 var(--dark); }
  .chat-message.user .chat-avatar { margin-left: 8px; background: linear-gradient(135deg, var(--secondary), #A855F7); color: #FFF; }
  .chat-message.ai .chat-avatar { margin-right: 8px; background: linear-gradient(135deg, var(--success), #059669); color: #FFF; }
  .chat-content { max-width: 75%; padding: 12px 16px; border-radius: 12px; border: 3px solid var(--dark);
    font-family: 'Comic Neue', cursive; font-size: 14px; font-weight: 700; line-height: 1.6; box-shadow: 3px 3px 0 var(--dark); }
  .chat-message.user .chat-content { background: linear-gradient(135deg, var(--secondary), #A855F7); color: #FFF; }
  .chat-message.ai .chat-content { background: #FFF; color: var(--dark); }
  #aiChatForm { display: flex; padding: 15px; border-top: 4px solid var(--dark); gap: 10px; }
  #aiChatInput { flex: 1; padding: 12px 16px; border: 3px solid var(--dark); border-radius: 25px;
    font-family: 'Comic Neue', cursive; font-weight: 700; background: var(--bg-warm); outline: none; }
  #aiChatSubmit { width: 48px; height: 48px; border-radius: 50%; background: linear-gradient(135deg, var(--danger), #F97316);
    border: 3px solid var(--dark); color: #FFF; cursor: pointer; box-shadow: 3px 3px 0 var(--dark); display: flex; align-items: center; justify-content: center; }

  /* Loading */
  .loading-overlay { position: fixed; top: 50%; left: 50%; transform: translate(-50%,-50%);
    background: #FFF; border: 4px solid var(--dark); padding: 40px; border-radius: var(--radius);
    box-shadow: 8px 8px 0 var(--dark); z-index: 9999; text-align: center; }
  .spinner { border: 5px solid var(--bg-warm); border-top: 5px solid var(--primary); border-radius: 50%;
    width: 50px; height: 50px; margin: 0 auto; animation: spin 1s linear infinite; }
  @keyframes spin { 0%{transform:rotate(0)} 100%{transform:rotate(360deg)} }
  .loading-text { font-family: 'Bangers', cursive; font-size: 1.2rem; color: var(--dark); margin-top: 16px; }

  /* Back button */
  .back-btn { position: fixed; top: 12px; left: 16px; z-index: 6000; display: none; }
  .back-btn button { background: linear-gradient(135deg, #F97316, var(--danger)); border: 3px solid var(--dark);
    color: #FFF; padding: 8px 16px; border-radius: 8px; font-family: 'Bangers', cursive; font-size: 1rem;
    cursor: pointer; box-shadow: var(--shadow); letter-spacing: 1px; }

  /* Footer */
  .footer { position: fixed; bottom: 10px; right: 10px; padding: 8px 16px;
    background: linear-gradient(135deg, var(--primary), var(--secondary)); border: 3px solid var(--dark);
    border-radius: 10px; box-shadow: var(--shadow); z-index: 100; }
  .footer p { font-family: 'Comic Neue', cursive; color: #FFF; font-weight: 700; font-size: 0.8rem; margin: 2px 0; }
  .footer a { color: var(--accent); text-decoration: none; }

  @media (max-width: 768px) {
    #createPanel, #aiChatContainer { width: 100%; }
    .gallery-grid { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
    #viewer { width: 98%; height: 92vh; }
    .footer { display: none; }
  }
  </style>
</head>
<body>
  <div class="header-info"><div class="title">AI BOOK MAKER</div></div>

  <!-- Floating Buttons -->
  <div id="createBtn" class="floating-btn floating-create" onclick="toggleCreatePanel(true)"><div class="icon"><i class="fas fa-magic"></i></div></div>
  <div id="aiBtn" class="floating-btn floating-ai" onclick="toggleAiChat(true)"><div class="icon"><i class="fas fa-robot"></i></div></div>
  <div id="pdfPromptBtn" class="floating-btn floating-pdf-btn active" data-pdf="prompt" onclick="switchPDF('prompt')"><div class="icon"><i class="fas fa-book"></i></div></div>
  <div id="pdfKtxBtn" class="floating-btn floating-pdf-btn" data-pdf="ktx" onclick="switchPDF('ktx')"><div class="icon"><i class="fas fa-train"></i></div></div>

  <div class="back-btn" id="backBtn"><button onclick="showGallery()"><i class="fas fa-arrow-left"></i> BACK</button></div>

  <!-- Gallery View -->
  <div id="galleryView">
    <div class="gallery-title">MY STORYBOOKS</div>
    <div class="gallery-grid" id="galleryGrid"></div>
  </div>

  <!-- FlipBook Viewer -->
  <div id="viewer"></div>

  <!-- Create Panel -->
  <div id="createPanel">
    <div class="panel-header">
      <h3><i class="fas fa-magic"></i> CREATE STORY</h3>
      <button class="panel-close" onclick="toggleCreatePanel(false)"><i class="fas fa-times"></i></button>
    </div>
    <div class="panel-body">
      <div class="form-group">
        <label class="form-label">What story?</label>
        <textarea id="storyPurpose" class="form-textarea" placeholder="e.g. A brave adventure to find a lost star..."></textarea>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Style</label>
          <select id="storyStyle" class="form-select">
            <option>Watercolor</option><option>Pastel</option><option>Cartoon</option>
            <option>Oil Painting</option><option>Pencil Sketch</option><option>Pop Art</option><option>Oriental</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Mood</label>
          <select id="storyMood" class="form-select">
            <option>Warm & Cozy</option><option>Mystical</option><option>Bright & Fun</option>
            <option>Adventurous</option><option>Serene</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Hero Name</label>
          <input id="childName" class="form-input" placeholder="Name" value="">
        </div>
        <div class="form-group">
          <label class="form-label">Age</label>
          <input id="childAge" class="form-input" type="number" value="6" min="3" max="12">
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">Hero Traits</label>
        <textarea id="childTraits" class="form-textarea" placeholder="e.g. Curly brown hair, blue pajamas, loves stars..."></textarea>
      </div>
      <button class="submit-btn" id="createSubmit" onclick="createStory()">
        <i class="fas fa-book-open"></i> CREATE STORY!
      </button>
      <div class="progress-section" id="progressSection">
        <div class="progress-title" id="progressTitle">Generating...</div>
        <div class="progress-bar-wrap"><div class="progress-bar-fill" id="progressBar" style="width:0%"></div></div>
        <div class="progress-detail" id="progressDetail"></div>
      </div>
    </div>
  </div>

  <!-- AI Chat -->
  <div id="aiChatContainer">
    <div id="aiChatHeader">
      <h3><i class="fas fa-robot"></i> AI ASSISTANT</h3>
      <button class="panel-close" onclick="toggleAiChat(false)"><i class="fas fa-times"></i></button>
    </div>
    <div id="aiChatMessages"></div>
    <form id="aiChatForm" onsubmit="submitQuestion(event)">
      <input type="text" id="aiChatInput" placeholder="Ask about the PDF..." autocomplete="off">
      <button type="submit" id="aiChatSubmit"><i class="fas fa-paper-plane"></i></button>
    </form>
  </div>

  <div class="footer">
    <p style="font-family:'Bangers',cursive;font-size:1rem;letter-spacing:1px">AI BOOK MAKER</p>
    <p>Powered by VLM + 3D FlipBook</p>
  </div>

<script>
    // ============================================================
    // JavaScript
    // ============================================================
    let fb = null;
    const viewer = document.getElementById('viewer');
    if (typeof pdfjsLib !== 'undefined') pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/pdf.worker.js';

    let currentView = 'gallery';
    let currentPdfKey = 'prompt';
    let isAiChatActive = false;
    let isCreatePanelActive = false;
    let activeStoryId = null;
    let pollInterval = null;
    let hasLoadedSummary = false;

    function $id(id) { return document.getElementById(id); }

    // --- Gallery ---
    async function loadGallery() {
      try {
        const resp = await fetch('/api/story/list');
        const data = await resp.json();
        const grid = $id('galleryGrid');
        let html = '';

        // Create card
        html += `<div class="story-card create-card" onclick="toggleCreatePanel(true)">
          <div class="icon"><i class="fas fa-plus-circle"></i></div>
          <div class="label">CREATE NEW</div>
        </div>`;

        // Sample PDF cards
        html += `<div class="story-card" onclick="openSamplePdf('prompt')">
          <div class="card-img"><div class="placeholder"><i class="fas fa-book" style="color:var(--primary)"></i></div></div>
          <div class="card-body"><div class="card-title">Sample: Prompt Book</div>
          <div class="card-meta">Built-in sample PDF</div>
          <div class="card-actions"><div class="card-btn view" onclick="event.stopPropagation();openSamplePdf('prompt')"><i class="fas fa-eye"></i> View</div></div></div>
        </div>`;
        html += `<div class="story-card" onclick="openSamplePdf('ktx')">
          <div class="card-img"><div class="placeholder"><i class="fas fa-train" style="color:#F97316"></i></div></div>
          <div class="card-body"><div class="card-title">Sample: KTX Magazine</div>
          <div class="card-meta">Built-in sample PDF</div>
          <div class="card-actions"><div class="card-btn view" onclick="event.stopPropagation();openSamplePdf('ktx')"><i class="fas fa-eye"></i> View</div></div></div>
        </div>`;

        // Story cards
        if (data.stories) {
          for (const s of data.stories) {
            const thumbHtml = s.thumbnail ? `<img src="${s.thumbnail}" alt="${s.title}">` : `<div class="placeholder"><i class="fas fa-book-open" style="color:var(--secondary)"></i></div>`;
            const isDone = s.status === 'pdf_done' || s.status === 'verified';
            const btnClass = isDone ? 'view' : 'generating';
            const btnLabel = isDone ? '<i class="fas fa-eye"></i> View' : '<i class="fas fa-spinner fa-spin"></i> ' + (s.status || '...');
            const dlBtn = s.has_pdf ? `<div class="card-btn download" onclick="event.stopPropagation();downloadPdf('${s.story_id}')"><i class="fas fa-download"></i></div>` : '';

            html += `<div class="story-card" onclick="${isDone ? `openStory('${s.story_id}')` : ''}">
              <div class="card-img">${thumbHtml}</div>
              <div class="card-body">
                <div class="card-title">${s.title || s.purpose?.substring(0,25) || 'Untitled'}</div>
                <div class="card-meta">${s.child_name || ''} &middot; ${s.style || ''}</div>
                <div class="card-actions">
                  <div class="card-btn ${btnClass}" onclick="event.stopPropagation();${isDone ? `openStory('${s.story_id}')` : ''}">${btnLabel}</div>
                  ${dlBtn}
                </div>
              </div>
            </div>`;
          }
        }
        grid.innerHTML = html;
      } catch (e) {
        console.error('Gallery load error:', e);
      }
    }

    function showGallery() {
      currentView = 'gallery';
      $id('galleryView').style.display = 'block';
      $id('viewer').style.display = 'none';
      $id('backBtn').style.display = 'none';
      $id('createBtn').style.display = 'flex';
      $id('aiBtn').style.display = 'flex';
      document.querySelectorAll('.floating-pdf-btn').forEach(b => b.style.display = 'flex');
      if (fb) { viewer.innerHTML = ''; fb = null; }
      loadGallery();
    }

    function showViewer() {
      currentView = 'viewer';
      $id('galleryView').style.display = 'none';
      $id('viewer').style.display = 'block';
      $id('backBtn').style.display = 'block';
    }

    // --- FlipBook ---
    function createFlipBook(pages) {
      try {
        if (fb) { viewer.innerHTML = ''; fb = null; }
        const ww = window.innerWidth, wh = window.innerHeight;
        let w = ww * 0.94, h = wh * 0.88;
        viewer.style.width = Math.round(w) + 'px';
        viewer.style.height = Math.round(h) + 'px';
        const valid = pages.map(p => p && p.src ? p : {src:'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSIjZjVmNWY1Ii8+PC9zdmc+',thumb:''});
        fb = new FlipBook(viewer, {
          pages: valid, viewMode: 'webgl', autoSize: true, flipDuration: 800, backgroundColor: '#fff',
          sound: true, assets: {flipMp3:'/static/turnPage2.mp3', hardFlipMp3:'/static/turnPage2.mp3'},
          controlsProps: { enableFullscreen:true, enableToc:true, enableDownload:false, enableZoom:true,
            enableSearch:true, enableAutoPlay:true, enableSound:true, layout:10, skin:'light',
            thumbnails:true, autoHideControls:false, controlsTimeout:8000, paddingTop:10, paddingLeft:10, paddingRight:10, paddingBottom:10 }
        });
        showViewer();
      } catch (e) { console.error('FlipBook error:', e); }
    }

    // --- Open story in FlipBook ---
    async function openStory(storyId) {
      try {
        showLoading('Loading story...');
        const resp = await fetch(`/api/story/${storyId}/flipbook`);
        const data = await resp.json();
        hideLoading();
        if (data.pages && data.pages.length > 0) {
          createFlipBook(data.pages);
          activeStoryId = storyId;
        } else {
          alert('No pages found');
        }
      } catch (e) { hideLoading(); console.error(e); }
    }

    async function openSamplePdf(key) {
      try {
        showLoading('Loading PDF...');
        currentPdfKey = key;
        await fetch(`/api/switch-pdf/${key}`, {method:'POST'});
        // Poll until cached
        let attempts = 0;
        while (attempts < 60) {
          const resp = await fetch('/api/cached-pdf');
          const data = await resp.json();
          if (data.status === 'completed' && data.pages) {
            hideLoading();
            createFlipBook(data.pages);
            updatePdfBtnState(key);
            return;
          }
          await new Promise(r => setTimeout(r, 1500));
          attempts++;
        }
        hideLoading();
      } catch (e) { hideLoading(); console.error(e); }
    }

    function updatePdfBtnState(key) {
      document.querySelectorAll('.floating-pdf-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.pdf === key);
      });
    }

    function switchPDF(key) { openSamplePdf(key); }

    function downloadPdf(storyId) {
      window.open(`/api/story/${storyId}/pdf`, '_blank');
    }

    // --- Create Story ---
    const STYLE_MAP = {'Watercolor':'수채화 동화','Pastel':'파스텔 일러스트','Cartoon':'만화 스타일','Oil Painting':'유화풍','Pencil Sketch':'연필 스케치','Pop Art':'팝아트','Oriental':'동양화'};
    const MOOD_MAP = {'Warm & Cozy':'따뜻하고 포근한','Mystical':'신비롭고 몽환적인','Bright & Fun':'밝고 유쾌한','Adventurous':'모험적이고 용감한','Serene':'잔잔하고 서정적인'};

    async function createStory() {
      const purpose = $id('storyPurpose').value.trim();
      if (!purpose) { alert('Please describe your story!'); return; }
      const style = STYLE_MAP[$id('storyStyle').value] || $id('storyStyle').value;
      const mood = MOOD_MAP[$id('storyMood').value] || $id('storyMood').value;
      const name = $id('childName').value.trim() || 'Hero';
      const age = parseInt($id('childAge').value) || 6;
      const traits = $id('childTraits').value.trim();

      $id('createSubmit').disabled = true;
      $id('progressSection').classList.add('active');
      $id('progressTitle').textContent = 'Starting...';
      $id('progressBar').style.width = '0%';

      try {
        const resp = await fetch('/api/story/create', {
          method: 'POST', headers: {'Content-Type':'application/json'},
          body: JSON.stringify({purpose, style, mood, child_name:name, child_age:age, child_traits:traits})
        });
        const data = await resp.json();
        if (data.error) { alert(data.error); $id('createSubmit').disabled = false; return; }
        activeStoryId = data.story_id;
        startProgressPoll(data.story_id);
      } catch (e) {
        alert('Error: ' + e.message);
        $id('createSubmit').disabled = false;
      }
    }

    function startProgressPoll(storyId) {
      if (pollInterval) clearInterval(pollInterval);
      pollInterval = setInterval(async () => {
        try {
          const resp = await fetch(`/api/story/status/${storyId}`);
          const data = await resp.json();
          const pct = data.progress || 0;
          $id('progressBar').style.width = pct + '%';
          $id('progressDetail').textContent = data.detail || data.step || '';
          $id('progressTitle').textContent = `Generating... ${pct}%`;

          if (data.status === 'completed' || data.status === 'pdf_done' || data.status === 'verified') {
            clearInterval(pollInterval); pollInterval = null;
            $id('progressTitle').textContent = 'Done!';
            $id('progressBar').style.width = '100%';
            $id('createSubmit').disabled = false;
            loadGallery();
          } else if (data.status === 'error') {
            clearInterval(pollInterval); pollInterval = null;
            $id('progressTitle').textContent = 'Error!';
            $id('progressDetail').textContent = data.detail || 'Unknown error';
            $id('createSubmit').disabled = false;
          }
        } catch (e) { console.error(e); }
      }, 3000);
    }

    function toggleCreatePanel(show) {
      $id('createPanel').classList.toggle('active', show);
      isCreatePanelActive = show;
    }

    // --- AI Chat ---
    function toggleAiChat(show) {
      $id('aiChatContainer').classList.toggle('active', show);
      isAiChatActive = show;
      if (show && !hasLoadedSummary) loadSummary();
    }

    async function loadSummary() {
      try {
        addChatMsg('Loading PDF summary...', false);
        const resp = await fetch('/api/ai/summarize-pdf');
        const data = await resp.json();
        $id('aiChatMessages').innerHTML = '';
        addChatMsg(data.summary || 'Ask me anything about the PDF!', false);
        hasLoadedSummary = true;
      } catch (e) {
        addChatMsg('Ready! Ask me about the PDF.', false);
        hasLoadedSummary = true;
      }
    }

    function addChatMsg(content, isUser) {
      const el = document.createElement('div');
      el.className = `chat-message ${isUser ? 'user' : 'ai'}`;
      let rendered = content;
      if (!isUser && typeof marked !== 'undefined') {
        try { rendered = marked.parse(content); } catch(e) {}
      }
      el.innerHTML = `<div class="chat-avatar"><i class="fas ${isUser?'fa-user':'fa-robot'}"></i></div>
        <div class="chat-content">${rendered}</div>`;
      $id('aiChatMessages').appendChild(el);
      $id('aiChatMessages').scrollTop = $id('aiChatMessages').scrollHeight;
    }

    async function submitQuestion(e) {
      e.preventDefault();
      const q = $id('aiChatInput').value.trim();
      if (!q) return;
      addChatMsg(q, true);
      $id('aiChatInput').value = '';
      try {
        const resp = await fetch('/api/ai/query-pdf', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({query: q})
        });
        const data = await resp.json();
        addChatMsg(data.answer || data.error || 'No response', false);
      } catch (e) { addChatMsg('Error: ' + e.message, false); }
    }

    // --- Loading ---
    function showLoading(msg) {
      hideLoading();
      const el = document.createElement('div');
      el.className = 'loading-overlay'; el.id = 'loadingOverlay';
      el.innerHTML = `<div class="spinner"></div><div class="loading-text">${msg||'Loading...'}</div>`;
      document.body.appendChild(el);
    }
    function hideLoading() { const el = $id('loadingOverlay'); if (el) el.remove(); }

    // --- Init ---
    document.addEventListener('DOMContentLoaded', () => {
      loadGallery();
    });
</script>
</body>
</html>
"""

# ============================================================
# [15] Main
# ============================================================
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", 7860)))
