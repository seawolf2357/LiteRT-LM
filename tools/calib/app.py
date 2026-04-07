"""
🖥️ 모니터 패널 캘리브레이션 계측 시스템 v4
Auto Screen Capture + Marker Detection + ICC Profile

v4 개선사항:
  1. JS 캡처를 현재 탭 우선(preferCurrentTab) + DPI 보정(devicePixelRatio)
  2. 마커 크기를 이미지 비례 동적 계산 (60~150px)
  3. 마커 감지 적응형 threshold(80) + 컴팩트성 검증으로 노이즈 필터링
  4. ROI 추출 시 border 오프셋을 마커 bbox에서 역산하여 정확히 보정
  5. 비율 검증(±5%) + 중앙 crop 후 리사이즈로 왜곡 방지
  6. 전체화면+캡처 통합 워크플로우 버튼 추가
"""

import gradio as gr
import numpy as np
from PIL import Image, ImageDraw
import struct
import io
import base64
import tempfile
from datetime import datetime

# ============================================================
# 색상 과학 엔진
# ============================================================

def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def srgb_to_xyz(rgb):
    linear = srgb_to_linear(rgb)
    M = np.array([[0.4124564,0.3575761,0.1804375],
                  [0.2126729,0.7151522,0.0721750],
                  [0.0193339,0.1191920,0.9503041]])
    return M @ linear

def xyz_to_lab(xyz, wr=None):
    if wr is None: wr = np.array([0.95047, 1.0, 1.08883])
    r = xyz / wr
    def f(t):
        d = 6/29
        return np.where(t > d**3, t**(1/3), t/(3*d**2) + 4/29)
    fx, fy, fz = f(r[0]), f(r[1]), f(r[2])
    return np.array([116*fy-16, 500*(fx-fy), 200*(fy-fz)])

def rgb_to_lab(rgb):
    return xyz_to_lab(srgb_to_xyz(rgb))

def delta_e_2000(lab1, lab2):
    L1,a1,b1 = lab1; L2,a2,b2 = lab2
    C1=np.sqrt(a1**2+b1**2); C2=np.sqrt(a2**2+b2**2)
    Ca=(C1+C2)/2; G=0.5*(1-np.sqrt(Ca**7/(Ca**7+25**7)))
    a1p=a1*(1+G); a2p=a2*(1+G)
    C1p=np.sqrt(a1p**2+b1**2); C2p=np.sqrt(a2p**2+b2**2)
    h1p=np.degrees(np.arctan2(b1,a1p))%360; h2p=np.degrees(np.arctan2(b2,a2p))%360
    dLp=L2-L1; dCp=C2p-C1p
    if C1p*C2p==0: dhp=0
    elif abs(h2p-h1p)<=180: dhp=h2p-h1p
    elif h2p-h1p>180: dhp=h2p-h1p-360
    else: dhp=h2p-h1p+360
    dHp=2*np.sqrt(C1p*C2p)*np.sin(np.radians(dhp/2))
    Lpa=(L1+L2)/2; Cpa=(C1p+C2p)/2
    if C1p*C2p==0: hpa=h1p+h2p
    elif abs(h1p-h2p)<=180: hpa=(h1p+h2p)/2
    elif h1p+h2p<360: hpa=(h1p+h2p+360)/2
    else: hpa=(h1p+h2p-360)/2
    T=1-0.17*np.cos(np.radians(hpa-30))+0.24*np.cos(np.radians(2*hpa))+0.32*np.cos(np.radians(3*hpa+6))-0.20*np.cos(np.radians(4*hpa-63))
    SL=1+0.015*(Lpa-50)**2/np.sqrt(20+(Lpa-50)**2)
    SC=1+0.045*Cpa; SH=1+0.015*Cpa*T
    RT=-2*np.sqrt(Cpa**7/(Cpa**7+25**7))*np.sin(np.radians(60*np.exp(-((hpa-275)/25)**2)))
    return np.sqrt((dLp/SL)**2+(dCp/SC)**2+(dHp/SH)**2+RT*(dCp/SC)*(dHp/SH))

def delta_e_rating(de):
    if de<1: return "◎ 완벽","#00c853"
    elif de<2: return "○ 우수","#64dd17"
    elif de<3: return "△ 양호","#ffd600"
    elif de<5: return "▽ 보통","#ff9100"
    else: return "✕ 불량","#ff1744"

# ============================================================
# 마커 시스템
# ============================================================

# 코너 마커 색상 (각각 고유, 테두리와도 다른 색상)
MARKER_COLORS = {
    'TL': (255, 0, 128),    # 로즈핑크
    'TR': (0, 255, 128),    # 스프링그린
    'BL': (128, 0, 255),    # 바이올렛
    'BR': (0, 128, 255),    # 도저블루
}
BORDER_WIDTH = 8            # 테두리 폭 (px)
BORDER_COLOR = (255, 128, 0)  # 오렌지 테두리 (마커와 완전히 다른 색)

def get_marker_size(w, h):
    """이미지 크기에 비례한 마커 크기 (최소 60px, 최대 150px)"""
    return max(60, min(150, min(w, h) // 8))

def add_marker_frame(img_array):
    """이미지에 감지용 마커 프레임 추가

    구조: [마커프레임] → [원본 이미지]
    프레임이 추가된 이미지 반환 + 프레임 내부(원본) 크기 기록
    """
    h, w = img_array.shape[:2]
    ms = get_marker_size(w, h)
    bw = BORDER_WIDTH
    pad = ms  # 마커 크기만큼 패딩
    
    # 프레임 포함 새 이미지
    new_h = h + pad * 2
    new_w = w + pad * 2
    framed = np.zeros((new_h, new_w, 3), dtype=np.uint8)
    framed[:, :] = (30, 30, 30)  # 어두운 배경
    
    # 테두리 그리기
    framed[pad-bw:pad, pad-bw:pad+w+bw] = BORDER_COLOR           # 상단
    framed[pad+h:pad+h+bw, pad-bw:pad+w+bw] = BORDER_COLOR       # 하단
    framed[pad-bw:pad+h+bw, pad-bw:pad] = BORDER_COLOR           # 좌측
    framed[pad-bw:pad+h+bw, pad+w:pad+w+bw] = BORDER_COLOR       # 우측
    
    # 4개 코너 마커
    framed[0:ms, 0:ms] = MARKER_COLORS['TL']                      # 좌상
    framed[0:ms, new_w-ms:new_w] = MARKER_COLORS['TR']            # 우상
    framed[new_h-ms:new_h, 0:ms] = MARKER_COLORS['BL']            # 좌하
    framed[new_h-ms:new_h, new_w-ms:new_w] = MARKER_COLORS['BR']  # 우하
    
    # 원본 이미지 삽입
    framed[pad:pad+h, pad:pad+w] = img_array[:, :, :3]
    
    return framed, (w, h)

def color_distance(pixel, target):
    """RGB 유클리드 거리"""
    return np.sqrt(np.sum((np.array(pixel, dtype=float) - np.array(target, dtype=float))**2))

def find_marker_regions(img_array, target_color, threshold=80):
    """특정 색상의 마커 영역 중심 좌표 찾기 (적응형 threshold)"""
    h, w = img_array.shape[:2]
    min_pixels = max(10, (h * w) // 50000)  # 이미지 크기에 비례한 최소 픽셀 수

    # 채널별 거리 계산 (벡터화)
    diff = img_array[:,:,:3].astype(float) - np.array(target_color, dtype=float)
    dist = np.sqrt(np.sum(diff**2, axis=2))
    mask = dist < threshold

    if np.sum(mask) < min_pixels:
        return None

    # 마스크의 중심 좌표
    ys, xs = np.where(mask)
    cy, cx = np.mean(ys), np.mean(xs)

    # 마커 바운딩박스
    min_y, max_y = np.min(ys), np.max(ys)
    min_x, max_x = np.min(xs), np.max(xs)

    # 컴팩트성 검증: bbox 면적 대비 실제 픽셀 비율 (스캐터 노이즈 필터링)
    bbox_area = max(1, (max_x - min_x + 1) * (max_y - min_y + 1))
    compactness = np.sum(mask) / bbox_area
    if compactness < 0.3:  # 30% 미만이면 노이즈로 판단
        return None

    return {
        'center': (int(cx), int(cy)),
        'bbox': (int(min_x), int(min_y), int(max_x), int(max_y)),
        'pixel_count': int(np.sum(mask))
    }

def detect_pattern_roi(capture_array):
    """캡처 이미지에서 마커 프레임을 감지하고 패턴 영역(ROI) 추출
    
    감지 전략:
    1. 4색 코너 마커 탐색 (각각 독립적 색상)
    2. 마커 위치로 패턴 바운딩박스 계산
    3. 폴백: 오렌지 테두리 탐색
    
    Returns: (roi_image, detection_info) or (None, error_msg)
    """
    if capture_array is None:
        return None, "캡처 이미지가 없습니다."
    
    h, w = capture_array.shape[:2]
    cap = capture_array[:,:,:3]
    
    # 4개 마커 탐색 (적응형 threshold)
    min_marker_px = max(20, (h * w) // 50000)
    markers_found = {}
    for name, color in MARKER_COLORS.items():
        result = find_marker_regions(cap, color, threshold=80)
        if result and result['pixel_count'] >= min_marker_px:
            markers_found[name] = result
    
    info_lines = [f"감지된 마커: {len(markers_found)}/4"]
    for name, data in markers_found.items():
        cx, cy = data['center']
        bx1, by1, bx2, by2 = data['bbox']
        info_lines.append(f"  {name}: center=({cx},{cy}) bbox=({bx1},{by1})-({bx2},{by2}) px={data['pixel_count']}")
    
    # ── 방법 1: TL + BR 마커 쌍으로 ROI ──
    if 'TL' in markers_found and 'BR' in markers_found:
        tl_bbox = markers_found['TL']['bbox']  # (min_x, min_y, max_x, max_y)
        br_bbox = markers_found['BR']['bbox']

        # 마커 크기를 bbox에서 역산 (스케일링 대응)
        tl_w = tl_bbox[2] - tl_bbox[0]
        tl_h = tl_bbox[3] - tl_bbox[1]
        br_w = br_bbox[2] - br_bbox[0]
        br_h = br_bbox[3] - br_bbox[1]

        # 패턴 영역 = 마커 영역 바깥쪽 끝에서 마커 크기만큼 안쪽
        # 구조: [마커ms][패딩(border포함)][패턴][패딩(border포함)][마커ms]
        # 마커 시작점 + 마커 크기 = 패딩 시작 → 패딩 = 마커 크기이므로
        # 패턴 시작 = 마커 시작 + 마커 크기 * 2  (대칭구조)
        roi_x1 = tl_bbox[0] + tl_w  # TL 마커 끝
        roi_y1 = tl_bbox[1] + tl_h  # TL 마커 끝
        roi_x2 = br_bbox[2] - br_w  # BR 마커 시작 (= 패턴 끝 + 패딩)
        roi_y2 = br_bbox[3] - br_h  # BR 마커 시작

        # 추가 보정: 마커↔패턴 사이에 border가 있으므로 그만큼 더 안쪽으로
        # border 두께를 마커 크기 비율로 역산
        avg_marker = (tl_w + tl_h + br_w + br_h) / 4
        # 원본에서 marker_size 대비 border_width 비율 = 8/marker_size
        # 캡처에서도 동일 비율 적용
        scaled_bw = max(1, int(avg_marker * BORDER_WIDTH / 60))  # 60 = 기본 marker_size 추정
        roi_x1 += scaled_bw
        roi_y1 += scaled_bw
        roi_x2 -= scaled_bw
        roi_y2 -= scaled_bw

        info_lines.append(f"  전략: TL+BR 코너 쌍 (마커크기≈{avg_marker:.0f}px, border보정={scaled_bw}px)")

    # ── 방법 2: 아무 대각선 마커 쌍 ──
    elif len(markers_found) >= 2:
        all_bboxes = list(markers_found.values())
        all_min_x = min(m['bbox'][0] for m in all_bboxes)
        all_min_y = min(m['bbox'][1] for m in all_bboxes)
        all_max_x = max(m['bbox'][2] for m in all_bboxes)
        all_max_y = max(m['bbox'][3] for m in all_bboxes)

        # 마커 평균 크기를 bbox에서 역산
        avg_w = np.mean([m['bbox'][2] - m['bbox'][0] for m in all_bboxes])
        avg_h = np.mean([m['bbox'][3] - m['bbox'][1] for m in all_bboxes])
        avg_ms = (avg_w + avg_h) / 2
        scaled_bw = max(1, int(avg_ms * BORDER_WIDTH / 60))

        roi_x1 = all_min_x + int(avg_w) + scaled_bw
        roi_y1 = all_min_y + int(avg_h) + scaled_bw
        roi_x2 = all_max_x - int(avg_w) - scaled_bw
        roi_y2 = all_max_y - int(avg_h) - scaled_bw

        info_lines.append(f"  전략: 복수 마커 외곽선 기반 (마커크기≈{avg_ms:.0f}px)")

    # ── 방법 3: 오렌지 테두리 탐색 ──
    elif len(markers_found) == 0:
        border_result = find_marker_regions(cap, BORDER_COLOR, threshold=80)
        if border_result and border_result['pixel_count'] > 50:
            bx1, by1, bx2, by2 = border_result['bbox']
            bw = BORDER_WIDTH
            roi_x1 = bx1 + bw
            roi_y1 = by1 + bw
            roi_x2 = bx2 - bw
            roi_y2 = by2 - bw
            info_lines.append(f"  전략: 테두리 색상 감지")
        else:
            return None, "마커/테두리를 찾을 수 없습니다.\n" + "\n".join(info_lines)
    else:
        # 마커 1개만 발견 → 부정확
        m = list(markers_found.values())[0]
        return None, f"마커 1개만 감지 (최소 2개 필요)\n" + "\n".join(info_lines)
    
    # 범위 클램핑
    roi_x1 = max(0, int(roi_x1))
    roi_y1 = max(0, int(roi_y1))
    roi_x2 = min(w, int(roi_x2))
    roi_y2 = min(h, int(roi_y2))
    
    roi_w = roi_x2 - roi_x1
    roi_h = roi_y2 - roi_y1
    
    if roi_w < 50 or roi_h < 50:
        return None, f"ROI 크기 부족 ({roi_w}x{roi_h})\n" + "\n".join(info_lines)
    
    roi = cap[roi_y1:roi_y2, roi_x1:roi_x2]
    info_lines.append(f"  ✅ ROI: ({roi_x1},{roi_y1})-({roi_x2},{roi_y2}) = {roi_w}x{roi_h}")
    
    return roi, "\n".join(info_lines)


# ============================================================
# ColorChecker 기준값
# ============================================================

COLORCHECKER = {
    "1-DarkSkin":(115,82,68), "2-LightSkin":(194,150,130),
    "3-BlueSky":(98,122,157), "4-Foliage":(87,108,67),
    "5-BlueFlower":(133,128,177), "6-BluishGreen":(103,189,170),
    "7-Orange":(214,126,44), "8-PurplishBlue":(80,91,166),
    "9-ModerateRed":(193,90,99), "10-Purple":(94,60,108),
    "11-YellowGreen":(157,188,64), "12-OrangeYellow":(224,163,46),
    "13-Blue":(56,61,150), "14-Green":(70,148,73),
    "15-Red":(175,54,60), "16-Yellow":(231,199,31),
    "17-Magenta":(187,86,149), "18-Cyan":(8,133,161),
    "19-White":(243,243,242), "20-Neutral8":(200,200,200),
    "21-Neutral6.5":(160,160,160), "22-Neutral5":(122,122,121),
    "23-Neutral3.5":(85,85,85), "24-Black":(52,52,52),
}

# ============================================================
# 테스트 패턴 생성 (마커 포함)
# ============================================================

def generate_colorchecker(w=1200, h=800):
    img = Image.new('RGB', (w,h), (40,40,40))
    draw = ImageDraw.Draw(img)
    colors = list(COLORCHECKER.items())
    cols, rows = 6, 4
    mg = 30
    pw = (w - mg*(cols+1)) // cols
    ph = (h - mg*(rows+1) - 60) // rows
    draw.text((w//2-150, 10), "Reference ColorChecker 24", fill=(200,200,200))
    for idx, (name,(r,g,b)) in enumerate(colors):
        row, col = idx//cols, idx%cols
        x = mg + col*(pw+mg)
        y = 50 + mg + row*(ph+mg)
        draw.rectangle([x,y,x+pw,y+ph], fill=(r,g,b))
        br = 0.299*r+0.587*g+0.114*b
        tc = (0,0,0) if br>128 else (255,255,255)
        draw.text((x+5,y+5), name.split('-')[0], fill=tc)
        draw.text((x+5,y+ph-18), f"({r},{g},{b})", fill=tc)
    return np.array(img)

def generate_grayscale(w=1200, h=400, steps=32):
    img = Image.new('RGB', (w,h), (0,0,0))
    draw = ImageDraw.Draw(img)
    sw = w // steps
    draw.text((w//2-100, 5), "Grayscale Reference Ramp", fill=(200,200,200))
    for i in range(steps):
        v = int(255*i/(steps-1))
        x = i*sw
        draw.rectangle([x, 30, x+sw, h-30], fill=(v,v,v))
        if i%4==0:
            tc = (255,255,255) if v<128 else (0,0,0)
            draw.text((x+2, h//2-5), str(v), fill=tc)
    return np.array(img)

def generate_gamma_check(w=1200, h=600):
    img = Image.new('RGB', (w,h), (30,30,30))
    draw = ImageDraw.Draw(img)
    draw.text((w//2-120, 5), "Gamma Verification Pattern", fill=(200,200,200))
    steps = 11
    pw = (w-40)//steps
    ph = (h-100)//2
    for i in range(steps):
        pct = i/(steps-1)
        v = int(255*pct)
        x = 20+i*pw
        draw.rectangle([x,40,x+pw-4,40+ph-10], fill=(v,v,v))
        ys = 40+ph
        cs = 2
        for cy in range(ys, ys+ph-10, cs):
            for cx in range(x, x+pw-4, cs):
                is_w = ((cx-x)//cs + (cy-ys)//cs)%2
                c = 255 if is_w else 0
                draw.rectangle([cx,cy,cx+cs-1,cy+cs-1], fill=(c,c,c))
        tc = (255,255,255) if v<128 else (0,0,0)
        draw.text((x+pw//2-10, 40+ph//2-5), f"{int(pct*100)}%", fill=tc)
    draw.text((20, h-25), "상단=솔리드, 하단=체커보드 → γ2.2에서 밝기 동일", fill=(160,160,160))
    return np.array(img)

def generate_rgb_ramps(w=1200, h=500):
    img = Image.new('RGB', (w,h), (30,30,30))
    draw = ImageDraw.Draw(img)
    draw.text((w//2-80, 5), "RGB Channel Ramps", fill=(200,200,200))
    bh = (h-80)//3
    for ci, (cn, ch) in enumerate([("Red",0),("Green",1),("Blue",2)]):
        y = 35+ci*(bh+10)
        draw.text((5,y+2), cn, fill=(200,200,200))
        for x in range(w):
            v = int(255*x/(w-1))
            px = [0,0,0]; px[ch] = v
            draw.line([(x,y+20),(x,y+20+bh-25)], fill=tuple(px))
    return np.array(img)

def generate_whitebalance(w=1200, h=600):
    img = Image.new('RGB', (w,h), (30,30,30))
    draw = ImageDraw.Draw(img)
    draw.text((w//2-130, 5), "White Balance & Neutral Patches", fill=(200,200,200))
    ww, wh = 500, 280
    wx = (w-ww)//2
    draw.rectangle([wx,40,wx+ww,40+wh], fill=(255,255,255))
    draw.text((wx+10,50), "White (255,255,255)", fill=(0,0,0))
    grays = [("N9.5",243),("N8",200),("N6.5",160),("N5",122),("N3.5",85),("N2",52)]
    gpw = (w-40)//len(grays)
    for i,(nm,v) in enumerate(grays):
        x = 20+i*gpw
        y = 40+wh+30
        draw.rectangle([x,y,x+gpw-4,y+140], fill=(v,v,v))
        tc = (255,255,255) if v<128 else (0,0,0)
        draw.text((x+5,y+5), f"{nm}({v})", fill=tc)
    return np.array(img)


PATTERN_GENERATORS = {
    "ColorChecker 24색": generate_colorchecker,
    "그레이스케일 32단계": generate_grayscale,
    "RGB 채널 램프": generate_rgb_ramps,
    "감마 검증 패턴": generate_gamma_check,
    "화이트밸런스 패치": generate_whitebalance,
}

def create_framed_pattern(pattern_type):
    """마커 프레임이 포함된 기준 패턴 생성 → 미리보기 + 다운로드 + State"""
    gen = PATTERN_GENERATORS.get(pattern_type, generate_colorchecker)
    raw = gen()
    framed, inner_size = add_marker_frame(raw)
    
    # PNG 저장
    pil = Image.fromarray(framed)
    path = tempfile.mktemp(suffix=".png")
    pil.save(path, "PNG", compress_level=0)
    
    return framed, path, raw, inner_size, f"✅ {pattern_type} 생성 완료 ({raw.shape[1]}x{raw.shape[0]})"


# ============================================================
# 스크린캡처 분석 (핵심)
# ============================================================

def extract_checker_patches(img_array, cols=6, rows=4):
    """이미지에서 ColorChecker 패치별 평균 RGB 추출"""
    h, w = img_array.shape[:2]
    mg = 30
    pw = (w - mg*(cols+1)) // cols
    ph = (h - mg*(rows+1) - 60) // rows
    
    extracted = {}
    names = list(COLORCHECKER.keys())
    for idx, name in enumerate(names):
        row, col = idx//cols, idx%cols
        x = mg + col*(pw+mg)
        y = 50 + mg + row*(ph+mg)
        # 패치 중앙 60% 샘플링
        mx, my = int(pw*0.2), int(ph*0.2)
        x1, y1 = min(x+mx, w-1), min(y+my, h-1)
        x2, y2 = min(x+pw-mx, w), min(y+ph-my, h)
        if x2>x1 and y2>y1:
            region = img_array[y1:y2, x1:x2, :3]
            extracted[name] = tuple(np.round(np.mean(region, axis=(0,1))).astype(int))
        else:
            extracted[name] = (0,0,0)
    return extracted


def run_full_analysis(ref_raw, ref_inner_size, captured_base64, pattern_type):
    """
    전체 분석 파이프라인:
    1. base64 캡처 디코딩
    2. 마커 감지 → ROI 추출
    3. 기준 이미지 크기로 리사이즈
    4. 픽셀 비교 + Delta E 분석
    """
    if ref_raw is None:
        return None, None, "❌ 기준 이미지가 없습니다. ① 탭에서 먼저 패턴을 생성하세요.", None, None
    
    if captured_base64 is None or not captured_base64.strip():
        return None, None, "❌ 캡처 데이터가 없습니다. 📸 버튼을 클릭하세요.", None, None
    
    # 1. base64 → numpy
    try:
        if ',' in captured_base64:
            captured_base64 = captured_base64.split(',', 1)[1]
        img_bytes = base64.b64decode(captured_base64)
        cap_pil = Image.open(io.BytesIO(img_bytes)).convert('RGB')
        cap_array = np.array(cap_pil)
    except Exception as e:
        return None, None, f"❌ 캡처 디코딩 오류: {str(e)}", None, None
    
    cap_h, cap_w = cap_array.shape[:2]
    
    # 2. 마커 감지 → ROI 추출
    roi, detect_info = detect_pattern_roi(cap_array)
    
    if roi is None:
        # 폴백: 전체 캡처를 사용 (마커 없이)
        roi = cap_array
        detect_info += "\n⚠️ 마커 미감지 → 전체 캡처를 분석에 사용"

    # 3. 비율 검증 + 중앙 crop + 기준 크기로 리사이즈
    ref_h, ref_w = ref_raw.shape[:2]
    ref_ratio = ref_w / ref_h
    roi_h, roi_w = roi.shape[:2]
    roi_ratio = roi_w / roi_h

    if abs(ref_ratio - roi_ratio) > 0.05:  # 비율 5% 이상 차이
        if roi_ratio > ref_ratio:  # ROI가 더 넓음 → 좌우 자르기
            new_w = int(roi_h * ref_ratio)
            offset = (roi_w - new_w) // 2
            roi = roi[:, offset:offset+new_w]
        else:  # ROI가 더 높음 → 상하 자르기
            new_h = int(roi_w / ref_ratio)
            offset = (roi_h - new_h) // 2
            roi = roi[offset:offset+new_h, :]
        detect_info += f"\n  비율 보정: {roi_w}x{roi_h}(ratio={roi_ratio:.3f}) → {roi.shape[1]}x{roi.shape[0]}(target={ref_ratio:.3f})"

    roi_pil = Image.fromarray(roi).resize((ref_w, ref_h), Image.LANCZOS)
    roi_resized = np.array(roi_pil)
    
    # 4. 분석 실행
    report_lines = []
    report_lines.append("━" * 56)
    report_lines.append("  📊 스크린캡처 자동 분석 결과")
    report_lines.append(f"  측정일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("━" * 56)
    report_lines.append(f"  캡처 원본:  {cap_w}x{cap_h}")
    report_lines.append(f"  감지 ROI:   {roi.shape[1]}x{roi.shape[0]}")
    report_lines.append(f"  기준 크기:  {ref_w}x{ref_h}")
    report_lines.append(f"  리사이즈:   {roi.shape[1]}x{roi.shape[0]} → {ref_w}x{ref_h}")
    report_lines.append(f"\n  [마커 감지]\n  {detect_info}")
    report_lines.append("")
    
    # ── ColorChecker 패치 분석 ──
    if "ColorChecker" in pattern_type:
        ref_patches = extract_checker_patches(ref_raw)
        cap_patches = extract_checker_patches(roi_resized)
        
        report_lines.append("┌────────────────┬────────────────┬────────────────┬───────┬──────┐")
        report_lines.append("│ 패치           │  기준 RGB      │  캡처 RGB      │  ΔE   │ 판정 │")
        report_lines.append("├────────────────┼────────────────┼────────────────┼───────┼──────┤")
        
        de_values = []
        for name in COLORCHECKER:
            r_rgb = np.array(ref_patches.get(name, COLORCHECKER[name]))
            c_rgb = np.array(cap_patches.get(name, (0,0,0)))
            de = delta_e_2000(rgb_to_lab(r_rgb), rgb_to_lab(c_rgb))
            rating, _ = delta_e_rating(de)
            de_values.append(de)
            
            sn = name[:14].ljust(14)
            rs = f"({r_rgb[0]:3d},{r_rgb[1]:3d},{r_rgb[2]:3d})"
            cs = f"({c_rgb[0]:3d},{c_rgb[1]:3d},{c_rgb[2]:3d})"
            report_lines.append(f"│ {sn} │ {rs:14s} │ {cs:14s} │{de:6.2f} │ {rating.split()[0]:4s} │")
        
        report_lines.append("└────────────────┴────────────────┴────────────────┴───────┴──────┘")
        
        avg_de = np.mean(de_values)
        max_de = np.max(de_values)
        min_de = np.min(de_values)
        max_name = list(COLORCHECKER.keys())[np.argmax(de_values)]
        min_name = list(COLORCHECKER.keys())[np.argmin(de_values)]
        avg_rating, _ = delta_e_rating(avg_de)
        
        report_lines.append(f"\n  [종합 통계]")
        report_lines.append(f"  평균 ΔE2000: {avg_de:.4f}  │ 판정: {avg_rating}")
        report_lines.append(f"  최대 ΔE2000: {max_de:.4f}  │ {max_name}")
        report_lines.append(f"  최소 ΔE2000: {min_de:.4f}  │ {min_name}")
        report_lines.append(f"  ΔE < 1.0: {sum(1 for d in de_values if d<1)}/24")
        report_lines.append(f"  ΔE < 2.0: {sum(1 for d in de_values if d<2)}/24")
        report_lines.append(f"  ΔE < 3.0: {sum(1 for d in de_values if d<3)}/24")
        report_lines.append(f"  ΔE ≥ 5.0: {sum(1 for d in de_values if d>=5)}/24")
    
    # ── 전체 픽셀 분석 ──
    report_lines.append(f"\n  [전체 픽셀 분석]")
    
    scale = max(1, min(ref_h, ref_w) // 150)
    ref_ds = ref_raw[::scale, ::scale, :3]
    cap_ds = roi_resized[::scale, ::scale, :3]
    ds_h, ds_w = ref_ds.shape[:2]
    
    de_map = np.zeros((ds_h, ds_w))
    rgb_diff = cap_ds.astype(float) - ref_ds.astype(float)
    
    for y in range(ds_h):
        for x in range(ds_w):
            r_lab = rgb_to_lab(ref_ds[y,x].astype(float))
            c_lab = rgb_to_lab(cap_ds[y,x].astype(float))
            de_map[y,x] = delta_e_2000(r_lab, c_lab)
    
    px_avg = np.mean(de_map)
    px_max = np.max(de_map)
    px_p95 = np.percentile(de_map, 95)
    
    report_lines.append(f"  샘플: {ds_w}x{ds_h} (1/{scale})")
    report_lines.append(f"  픽셀 평균 ΔE: {px_avg:.4f}")
    report_lines.append(f"  픽셀 최대 ΔE: {px_max:.4f}")
    report_lines.append(f"  95% 백분위:    {px_p95:.4f}")
    
    # 채널 편차
    dr = np.mean(rgb_diff[:,:,0])
    dg = np.mean(rgb_diff[:,:,1])
    db = np.mean(rgb_diff[:,:,2])
    report_lines.append(f"\n  [채널 편차] ΔR:{dr:+.2f}  ΔG:{dg:+.2f}  ΔB:{db:+.2f}")
    
    abs_d = [abs(dr), abs(dg), abs(db)]
    max_ch = ['Red','Green','Blue'][np.argmax(abs_d)]
    vals = [dr, dg, db]
    max_val = vals[np.argmax(abs_d)]
    if max(abs_d) < 1.0:
        bias = "⚪ 편향 없음 (균형)"
    else:
        direction = "과다" if max_val > 0 else "부족"
        bias = f"{'🔴🟢🔵'[np.argmax(abs_d)]} {max_ch} {direction} ({max_val:+.1f})"
    report_lines.append(f"  색편향: {bias}")
    
    report_lines.append("\n" + "━" * 56)
    
    # ── 히트맵 생성 ──
    de_norm = np.clip(de_map / 10, 0, 1)
    heatmap = np.zeros((ds_h, ds_w, 3), dtype=np.uint8)
    for y in range(ds_h):
        for x in range(ds_w):
            v = de_norm[y,x]
            if v < 0.2:
                r,g,b = int(255*v/0.2), 255, 0
            elif v < 0.5:
                t = (v-0.2)/0.3
                r,g,b = 255, int(255*(1-t)), 0
            else:
                t = min((v-0.5)/0.5, 1)
                r,g,b = 255, 0, 0
            heatmap[y,x] = [r,g,b]
    
    heatmap_full = np.array(Image.fromarray(heatmap).resize((ref_w, ref_h), Image.NEAREST))
    
    # ── 비교 이미지 ──
    comp_h = ref_h
    comp = np.zeros((comp_h, ref_w*2+10, 3), dtype=np.uint8)
    comp[:ref_h, :ref_w] = ref_raw[:,:,:3]
    comp[:ref_h, ref_w+10:] = roi_resized[:,:,:3]
    comp[:, ref_w:ref_w+10] = 60
    
    return roi_resized, heatmap_full, "\n".join(report_lines), comp, detect_info


def process_uploaded_capture(ref_raw, ref_inner_size, capture_image, pattern_type):
    """수동 업로드된 캡처 이미지 분석"""
    if capture_image is None:
        return None, None, "이미지를 업로드하세요.", None, ""
    
    # numpy → base64
    pil = Image.fromarray(capture_image)
    buf = io.BytesIO()
    pil.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode()
    
    return run_full_analysis(ref_raw, ref_inner_size, f"data:image/png;base64,{b64}", pattern_type)


# ============================================================
# ICC 프로파일 파서
# ============================================================

def parse_icc_profile(icc_file):
    if icc_file is None:
        return "ICC 파일을 업로드하세요.", None, None
    try:
        with open(icc_file.name, 'rb') as f: data = f.read()
    except:
        return "파일 읽기 오류", None, None
    if len(data) < 128:
        return "유효하지 않은 ICC 파일", None, None
    
    lines = []
    lines.append("━"*56)
    lines.append("  ICC 프로파일 분석 결과")
    lines.append("━"*56)
    
    profile_size = struct.unpack('>I', data[0:4])[0]
    ver_major, ver_minor = data[8], data[9]>>4
    dev_class = data[12:16].decode('ascii', errors='replace').strip('\x00')
    color_space = data[16:20].decode('ascii', errors='replace').strip('\x00')
    pcs = data[20:24].decode('ascii', errors='replace').strip('\x00')
    platform = data[40:44].decode('ascii', errors='replace').strip('\x00')
    year = struct.unpack('>H', data[24:26])[0]
    month = struct.unpack('>H', data[26:28])[0]
    day = struct.unpack('>H', data[28:30])[0]
    
    class_names = {'scnr':'Scanner','mntr':'Monitor','prtr':'Printer','link':'DeviceLink','spac':'ColorSpace','abst':'Abstract','nmcl':'NamedColor'}
    plat_names = {'APPL':'Apple','MSFT':'Microsoft','SGI ':'SGI','SUNW':'Sun'}
    
    lines.append(f"  크기: {profile_size:,}B | ICC v{ver_major}.{ver_minor}")
    lines.append(f"  디바이스: {class_names.get(dev_class,dev_class)} | 색공간: {color_space} | PCS: {pcs}")
    lines.append(f"  플랫폼: {plat_names.get(platform,platform)} | 생성: {year}-{month:02d}-{day:02d}")
    
    # 태그 파싱
    tag_count = struct.unpack('>I', data[128:132])[0]
    tags = {}
    for i in range(tag_count):
        off = 132+i*12
        if off+12>len(data): break
        sig = data[off:off+4].decode('ascii',errors='replace')
        tags[sig] = (struct.unpack('>I',data[off+4:off+8])[0], struct.unpack('>I',data[off+8:off+12])[0])
    
    # 화이트포인트
    primaries = {}
    if 'wtpt' in tags:
        o,s = tags['wtpt']
        if o+20<=len(data):
            wx=struct.unpack('>i',data[o+8:o+12])[0]/65536
            wy=struct.unpack('>i',data[o+12:o+16])[0]/65536
            wz=struct.unpack('>i',data[o+16:o+20])[0]/65536
            ss=wx+wy+wz
            if ss>0:
                cx,cy=wx/ss,wy/ss
                n=(cx-0.332)/(0.1858-cy) if (0.1858-cy)!=0 else 0
                cct=449*n**3+3525*n**2+6823.3*n+5520.33
                lines.append(f"\n  [화이트포인트] XYZ:({wx:.4f},{wy:.4f},{wz:.4f}) xy:({cx:.4f},{cy:.4f}) CCT:{cct:.0f}K")
    
    # 원색
    for ch,tag in [('Red','rXYZ'),('Green','gXYZ'),('Blue','bXYZ')]:
        if tag in tags:
            o,s=tags[tag]
            if o+20<=len(data):
                px=struct.unpack('>i',data[o+8:o+12])[0]/65536
                py=struct.unpack('>i',data[o+12:o+16])[0]/65536
                pz=struct.unpack('>i',data[o+16:o+20])[0]/65536
                ss=px+py+pz
                if ss>0: primaries[ch]=(px/ss,py/ss)
    
    if primaries:
        lines.append(f"\n  [원색 좌표 CIE xy]")
        srgb_p = {'Red':(0.64,0.33),'Green':(0.30,0.60),'Blue':(0.15,0.06)}
        for ch in ['Red','Green','Blue']:
            if ch in primaries:
                px,py=primaries[ch]; sx,sy=srgb_p[ch]
                lines.append(f"  {ch}: ({px:.4f},{py:.4f}) vs sRGB({sx},{sy})")
        
        def tri_area(p1,p2,p3):
            return 0.5*abs((p2[0]-p1[0])*(p3[1]-p1[1])-(p3[0]-p1[0])*(p2[1]-p1[1]))
        if all(c in primaries for c in ['Red','Green','Blue']):
            pa=tri_area(primaries['Red'],primaries['Green'],primaries['Blue'])
            sa=tri_area((0.64,0.33),(0.30,0.60),(0.15,0.06))
            da=tri_area((0.680,0.320),(0.265,0.690),(0.150,0.060))
            lines.append(f"  색역: sRGB {pa/sa*100:.1f}% | DCI-P3 {pa/da*100:.1f}%")
    
    # 감마/TRC
    gamma_data = {}
    for ch,tag in [('Red','rTRC'),('Green','gTRC'),('Blue','bTRC')]:
        if tag in tags:
            o,s=tags[tag]
            if o+12<=len(data):
                tt=data[o:o+4].decode('ascii',errors='replace')
                if tt=='curv':
                    cnt=struct.unpack('>I',data[o+8:o+12])[0]
                    if cnt==0: gamma_data[ch]={"type":"identity","gamma":1.0,"curve":None}
                    elif cnt==1:
                        gv=struct.unpack('>H',data[o+12:o+14])[0]/256
                        gamma_data[ch]={"type":"gamma","gamma":gv,"curve":None}
                    else:
                        curve=[]
                        for j in range(min(cnt,4096)):
                            if o+12+j*2+2<=len(data):
                                curve.append(struct.unpack('>H',data[o+12+j*2:o+14+j*2])[0]/65535)
                        eg=0
                        if len(curve)>10:
                            mi=len(curve)//2; iv=mi/(len(curve)-1); ov=curve[mi]
                            if iv>0 and ov>0: eg=np.log(ov)/np.log(iv)
                        gamma_data[ch]={"type":"curve","gamma":eg,"curve":curve}
                elif tt=='para':
                    ft=struct.unpack('>H',data[o+8:o+10])[0]
                    if ft==0 and o+16<=len(data):
                        gv=struct.unpack('>i',data[o+12:o+16])[0]/65536
                        gamma_data[ch]={"type":"para","gamma":gv,"curve":None}
    
    if gamma_data:
        lines.append(f"\n  [감마 TRC]")
        for ch in ['Red','Green','Blue']:
            if ch in gamma_data:
                gd=gamma_data[ch]
                lines.append(f"  {ch}: γ={gd['gamma']:.4f} ({gd['type']})")
        gammas=[g['gamma'] for g in gamma_data.values() if g['gamma']>0]
        if gammas:
            lines.append(f"  평균: {np.mean(gammas):.4f} | 채널편차: {max(gammas)-min(gammas):.4f}")
    
    lines.append(f"\n  [태그 {tag_count}개]")
    for sig in sorted(tags.keys()):
        o,s=tags[sig]
        lines.append(f"  {sig:6s} off:{o:6d} sz:{s:6d}")
    
    # desc
    if 'desc' in tags:
        o,s=tags['desc']
        try:
            dt=data[o:o+4].decode('ascii',errors='replace')
            if dt=='mluc':
                rc=struct.unpack('>I',data[o+8:o+12])[0]
                if rc>0 and o+28<=len(data):
                    so=struct.unpack('>I',data[o+20:o+24])[0]
                    sl=struct.unpack('>I',data[o+24:o+28])[0]
                    ao=o+so
                    if ao+sl<=len(data):
                        ds=data[ao:ao+sl].decode('utf-16-be',errors='replace').strip('\x00')
                        lines.insert(4, f"  프로파일: {ds}")
            elif dt=='desc':
                sl=struct.unpack('>I',data[o+8:o+12])[0]
                ds=data[o+12:o+12+sl-1].decode('ascii',errors='replace')
                lines.insert(4, f"  프로파일: {ds}")
        except: pass
    
    lines.append("\n"+"━"*56)
    
    # TRC 시각화
    trc_img = None
    if gamma_data:
        trc_img = _draw_trc(gamma_data)
    gamut_img = None
    if primaries and all(c in primaries for c in ['Red','Green','Blue']):
        gamut_img = _draw_gamut(primaries)
    
    return "\n".join(lines), trc_img, gamut_img


def _draw_trc(gamma_data, w=600, h=400):
    img = Image.new('RGB',(w,h),(25,25,30)); draw=ImageDraw.Draw(img)
    m=50; pw=w-2*m; ph=h-2*m
    for i in range(11):
        x=m+int(pw*i/10); y=m+int(ph*i/10)
        draw.line([(x,m),(x,m+ph)],fill=(50,50,55))
        draw.line([(m,y),(m+pw,y)],fill=(50,50,55))
    draw.text((w//2-50,5),"TRC / Gamma",fill=(200,200,200))
    # sRGB ref
    pts=[(m+int(pw*i/99), m+ph-int(ph*(i/99)**2.2)) for i in range(100)]
    draw.line(pts,fill=(80,80,80),width=1)
    colors={'Red':(255,80,80),'Green':(80,255,80),'Blue':(80,80,255)}
    for ch in ['Red','Green','Blue']:
        if ch not in gamma_data: continue
        gd=gamma_data[ch]; c=colors[ch]
        if gd['curve'] and len(gd['curve'])>1:
            cv=gd['curve']
            pts=[(m+int(pw*i/(len(cv)-1)), m+ph-int(ph*cv[i])) for i in range(len(cv))]
        elif gd['gamma']>0:
            pts=[(m+int(pw*i/99), m+ph-int(ph*(i/99)**gd['gamma'])) for i in range(100)]
        else: continue
        if len(pts)>1: draw.line(pts,fill=c,width=2)
    return np.array(img)

def _draw_gamut(primaries, w=500, h=500):
    img = Image.new('RGB',(w,h),(20,20,25)); draw=ImageDraw.Draw(img)
    m=50; pw=w-2*m; ph=h-2*m
    def xy2px(x,y): return (m+int(pw*x/0.8), m+ph-int(ph*y/0.9))
    for i in range(9):
        v=i*0.1; x=m+int(pw*v/0.8); y=m+ph-int(ph*v/0.9)
        draw.line([(x,m),(x,m+ph)],fill=(40,40,45))
        draw.line([(m,y),(m+pw,y)],fill=(40,40,45))
    draw.text((w//2-40,5),"CIE xy Gamut",fill=(200,200,200))
    # sRGB
    sp={'R':(0.64,0.33),'G':(0.30,0.60),'B':(0.15,0.06)}
    spts=[xy2px(*sp['R']),xy2px(*sp['G']),xy2px(*sp['B']),xy2px(*sp['R'])]
    draw.line(spts,fill=(150,150,150),width=1)
    # Profile
    ppts=[xy2px(*primaries['Red']),xy2px(*primaries['Green']),xy2px(*primaries['Blue']),xy2px(*primaries['Red'])]
    draw.line(ppts,fill=(0,255,200),width=2)
    for ch,c in [('Red',(255,50,50)),('Green',(50,255,50)),('Blue',(50,50,255))]:
        if ch in primaries:
            px,py=xy2px(*primaries[ch])
            draw.ellipse([px-4,py-4,px+4,py+4],fill=c)
    d65=xy2px(0.3127,0.329)
    draw.ellipse([d65[0]-3,d65[1]-3,d65[0]+3,d65[1]+3],fill=(255,255,255))
    draw.text((d65[0]+6,d65[1]-5),"D65",fill=(200,200,200))
    return np.array(img)


# ============================================================
# 스크린캡처 JavaScript
# ============================================================

CAPTURE_JS = """
async (current_val) => {
    try {
        const stream = await navigator.mediaDevices.getDisplayMedia({
            video: { displaySurface: 'browser', cursor: 'never' },
            preferCurrentTab: true,
            selfBrowserSurface: 'include'
        });
        const video = document.createElement('video');
        video.srcObject = stream;
        video.muted = true;
        await video.play();
        await new Promise(r => setTimeout(r, 500));

        const dpr = window.devicePixelRatio || 1;
        const srcW = video.videoWidth;
        const srcH = video.videoHeight;

        // DPI 보정: 물리 픽셀 → CSS 픽셀 크기로 정규화
        const outW = Math.round(srcW / dpr);
        const outH = Math.round(srcH / dpr);

        const canvas = document.createElement('canvas');
        canvas.width = outW;
        canvas.height = outH;
        const ctx = canvas.getContext('2d');
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(video, 0, 0, outW, outH);

        stream.getTracks().forEach(t => t.stop());
        video.remove();

        const dataUrl = canvas.toDataURL('image/png');
        return dataUrl;
    } catch(e) {
        console.error('Screen capture error:', e);
        return null;
    }
}
"""

FULLSCREEN_JS = """
() => {
    const imgs = document.querySelectorAll('#pattern-preview img');
    if (imgs.length > 0) {
        const img = imgs[imgs.length - 1];
        if (img.requestFullscreen) img.requestFullscreen();
        else if (img.webkitRequestFullscreen) img.webkitRequestFullscreen();
    }
    return [];
}
"""

# 전체화면 → 자동 캡처 → 전체화면 해제 통합 워크플로우
AUTO_CAPTURE_JS = """
async (current_val) => {
    try {
        // 1. 패턴 이미지를 전체화면으로 표시
        const imgs = document.querySelectorAll('#pattern-preview img');
        let patternImg = null;
        if (imgs.length > 0) {
            patternImg = imgs[imgs.length - 1];
            if (patternImg.requestFullscreen) await patternImg.requestFullscreen();
            else if (patternImg.webkitRequestFullscreen) patternImg.webkitRequestFullscreen();
        }

        // 2. 전체화면 안정화 대기
        await new Promise(r => setTimeout(r, 1500));

        // 3. 스크린캡처
        const stream = await navigator.mediaDevices.getDisplayMedia({
            video: { displaySurface: 'browser', cursor: 'never' },
            preferCurrentTab: true,
            selfBrowserSurface: 'include'
        });
        const video = document.createElement('video');
        video.srcObject = stream;
        video.muted = true;
        await video.play();
        await new Promise(r => setTimeout(r, 500));

        const dpr = window.devicePixelRatio || 1;
        const outW = Math.round(video.videoWidth / dpr);
        const outH = Math.round(video.videoHeight / dpr);

        const canvas = document.createElement('canvas');
        canvas.width = outW;
        canvas.height = outH;
        const ctx = canvas.getContext('2d');
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(video, 0, 0, outW, outH);

        stream.getTracks().forEach(t => t.stop());
        video.remove();

        // 4. 전체화면 해제
        if (document.fullscreenElement) {
            await document.exitFullscreen();
        }

        const dataUrl = canvas.toDataURL('image/png');
        return dataUrl;
    } catch(e) {
        // 에러 시에도 전체화면 해제
        if (document.fullscreenElement) {
            try { await document.exitFullscreen(); } catch(_) {}
        }
        console.error('Auto capture error:', e);
        return null;
    }
}
"""


# ============================================================
# Gradio UI
# ============================================================

def build_app():
    with gr.Blocks(
        title="모니터 캘리브레이션 v4",
        theme=gr.themes.Soft(),
        css="""
        .result-box { font-family: 'Courier New', monospace; font-size: 12px; line-height: 1.35; }
        .big-btn { min-height: 52px !important; font-size: 16px !important; }
        .capture-btn { min-height: 56px !important; font-size: 18px !important; background: #2196F3 !important; }
        """
    ) as app:
        
        # ── 공유 State ──
        ref_raw_state = gr.State(None)         # 원본 기준 이미지 (마커 없는)
        ref_inner_size_state = gr.State(None)   # 원본 크기 (w, h)
        pattern_type_state = gr.State("ColorChecker 24색")
        
        gr.Markdown("# 🖥️ 모니터 패널 캘리브레이션 계측 시스템 v4")
        gr.Markdown("**원클릭 자동 캡처** │ 마커 자동 감지 │ ROI 추출 │ Delta E 분석 │ ICC 프로파일")
        
        # ━━━━━ 탭 1: 기준 패턴 생성 ━━━━━
        with gr.Tab("① 기준 패턴 생성"):
            gr.Markdown("""
### 📐 기준 테스트 패턴 생성
패턴 선택 → 생성 → **전체화면** 표시 → **②탭에서 캡처** (자동 연동)  
> 💡 4색 코너 마커가 자동 삽입되어 캡처 시 패턴 영역을 자동 인식합니다
            """)
            
            with gr.Row():
                with gr.Column(scale=1):
                    pattern_select = gr.Dropdown(
                        choices=list(PATTERN_GENERATORS.keys()),
                        value="ColorChecker 24색",
                        label="패턴 유형"
                    )
                    gen_btn = gr.Button("🎨 기준 패턴 생성", variant="primary", elem_classes=["big-btn"])
                    fullscreen_btn = gr.Button("🔲 전체화면 미리보기", elem_classes=["big-btn"])
                    download_file = gr.File(label="📥 PNG 다운로드")
                    status_text = gr.Textbox(label="상태", interactive=False)
                
                with gr.Column(scale=2):
                    pattern_preview = gr.Image(label="기준 패턴 (마커 프레임 포함)", type="numpy", elem_id="pattern-preview")
            
            def on_generate(ptype):
                framed, path, raw, inner_sz, msg = create_framed_pattern(ptype)
                return framed, path, raw, inner_sz, ptype, msg
            
            gen_btn.click(
                on_generate,
                inputs=[pattern_select],
                outputs=[pattern_preview, download_file, ref_raw_state, ref_inner_size_state, pattern_type_state, status_text]
            )
            
            fullscreen_btn.click(fn=None, inputs=[], outputs=[], js=FULLSCREEN_JS)
        
        # ━━━━━ 탭 2: 자동 캡처 & 분석 ━━━━━
        with gr.Tab("② 자동 캡처 & 분석"):
            gr.Markdown("""
### 📸 원클릭 스크린캡처 → 자동 분석
**사용법:** ①탭에서 패턴 생성 후 아래 버튼으로 캡처
> **전체화면+캡처**: 패턴을 전체화면 표시 → 자동 캡처 → 전체화면 해제 (권장)
> **화면 캡처**: 현재 탭만 캡처 (DPI 자동 보정)
> 마커 프레임 자동 감지 → 패턴 ROI 추출 → 비율 보정 → Delta E 분석
            """)

            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("#### 기준 이미지 (자동 연동)")
                    ref_display = gr.Image(label="기준 패턴", type="numpy", interactive=False, height=250)

                    gr.Markdown("---")

                    # 캡처 base64 수신용 (숨김)
                    capture_base64 = gr.Textbox(visible=False, elem_id="capture-data")

                    auto_capture_btn = gr.Button("🎯 전체화면 + 캡처 (권장)", variant="primary", elem_classes=["capture-btn"])
                    capture_btn = gr.Button("📸 화면 캡처 (현재 탭)", variant="secondary", elem_classes=["big-btn"])

                    gr.Markdown("또는")
                    manual_upload = gr.Image(label="📁 캡처 이미지 수동 업로드", type="numpy", height=200)
                    manual_btn = gr.Button("🔬 수동 업로드 분석", variant="secondary")

                    detect_log = gr.Textbox(label="마커 감지 로그", lines=8, interactive=False)

                with gr.Column(scale=2):
                    captured_display = gr.Image(label="감지된 패턴 영역 (ROI)", type="numpy")
                    heatmap_display = gr.Image(label="🗺️ Delta E 히트맵 (초록=정확, 빨강=부정확)", type="numpy")
                    comparison_display = gr.Image(label="기준(좌) vs 캡처(우)", type="numpy")

            analysis_report = gr.Textbox(label="📊 분석 리포트", lines=38, elem_classes=["result-box"])

            # 탭 전환 시 기준 이미지 자동 표시
            def refresh_ref(raw):
                return raw

            ref_raw_state.change(refresh_ref, inputs=[ref_raw_state], outputs=[ref_display])

            # 전체화면+캡처 통합: JS → base64 → 분석
            auto_capture_btn.click(
                fn=None,
                inputs=[capture_base64],
                outputs=[capture_base64],
                js=AUTO_CAPTURE_JS
            )

            # 일반 캡처: JS → base64 → 분석
            capture_btn.click(
                fn=None,
                inputs=[capture_base64],
                outputs=[capture_base64],
                js=CAPTURE_JS
            )

            capture_base64.change(
                run_full_analysis,
                inputs=[ref_raw_state, ref_inner_size_state, capture_base64, pattern_type_state],
                outputs=[captured_display, heatmap_display, analysis_report, comparison_display, detect_log]
            )

            # 수동 업로드 분석
            manual_btn.click(
                process_uploaded_capture,
                inputs=[ref_raw_state, ref_inner_size_state, manual_upload, pattern_type_state],
                outputs=[captured_display, heatmap_display, analysis_report, comparison_display, detect_log]
            )
        
        # ━━━━━ 탭 3: ICC 프로파일 ━━━━━
        with gr.Tab("③ ICC 프로파일"):
            gr.Markdown("""
### 📄 ICC 프로파일 분석
모니터 ICC/ICM 파일의 색역, 감마, 화이트포인트를 파싱합니다.

**파일 위치:** Win: `C:\\Windows\\System32\\spool\\drivers\\color\\` │ Mac: 시스템설정→디스플레이→색상
            """)
            with gr.Row():
                with gr.Column():
                    icc_file = gr.File(label="ICC/ICM 업로드", file_types=[".icc",".icm"])
                    icc_btn = gr.Button("🔍 분석", variant="primary", elem_classes=["big-btn"])
                with gr.Column():
                    trc_img = gr.Image(label="TRC 감마 곡선", type="numpy")
                    gamut_img = gr.Image(label="CIE xy 색역", type="numpy")
            icc_report = gr.Textbox(label="ICC 리포트", lines=30, elem_classes=["result-box"])
            icc_btn.click(parse_icc_profile, inputs=[icc_file], outputs=[icc_report, trc_img, gamut_img])
        
        # ━━━━━ 탭 4: 가이드 ━━━━━
        with gr.Tab("ℹ️ 가이드"):
            gr.Markdown("""
### 📖 작동 원리

```
┌──────────────────────────────────────────────────────────────┐
│  ① 기준 패턴 생성 (RGB값 확정) + 마커 프레임 자동 삽입       │
│       ↓                                                       │
│  모니터에 전체화면 표시 (OS 색상관리 ICC 파이프라인 통과)      │
│       ↓                                                       │
│  ② [📸 화면 캡처] 클릭 → getDisplayMedia() 자동 스크린캡처   │
│       ↓                                                       │
│  마커 자동 감지 → 패턴 ROI 추출 → 기준 크기로 리사이즈       │
│       ↓                                                       │
│  기준 RGB vs 캡처 RGB → CIEDE2000 → 히트맵 + 리포트          │
└──────────────────────────────────────────────────────────────┘
```

### 🎯 마커 시스템
4색 코너 마커 + 오렌지 테두리로 캡처 이미지에서 패턴 영역을 자동 인식합니다.
- 좌상: 로즈핑크 (255,0,128)
- 우상: 스프링그린 (0,255,128)  
- 좌하: 바이올렛 (128,0,255)
- 우하: 도저블루 (0,128,255)
- 테두리: 오렌지 (255,128,0)

브라우저 UI, 작업표시줄 등이 포함되어도 마커 기반으로 패턴만 추출합니다.

### ⚠️ 주의사항
- 스크린캡처는 **OS 색상관리 후** 프레임버퍼를 캡처 (모니터 물리출력과는 다름)
- 하드웨어 계측기(i1Display, SpyderX)와는 측정 대상이 다름
- ICC 프로파일이 비활성화된 경우 기준=캡처 → ΔE≈0 (정상)
- PNG 무손실 형식 사용 필수 (JPEG 압축 아티팩트 방지)

### 📐 판정 기준
| ΔE2000 | 판정 | 의미 |
|--------|------|------|
| < 1.0 | ◎ 완벽 | 육안 구분 불가 |
| < 2.0 | ○ 우수 | 근접 비교 시 구분 |
| < 3.0 | △ 양호 | 주의 깊게 보면 구분 |
| < 5.0 | ▽ 보통 | 명확히 구분 가능 |
| ≥ 5.0 | ✕ 불량 | 뚜렷한 색차 |
            """)
        
        gr.Markdown("---")
        gr.Markdown("*Monitor Panel Calibration v4 │ Auto Capture + Marker Detection + ICC*")
    
    return app


if __name__ == "__main__":
    app = build_app()
    app.launch()