# HF Space `Heartsync/KID` 컨테이너 로그 분석

## 개요
Hugging Face Space `Heartsync/KID`의 빌드/런타임 로그를 분석한 결과입니다.
이 Space는 **맞춤형 동화 생성 SaaS** 앱으로, AXIS Emergence Engine + Kimi-K2.5 + Grok Imagine을 활용하여 15페이지 아동 동화를 자동 생성합니다.

## 앱 아키텍처

| 구성 요소 | 기술 |
|-----------|------|
| **프레임워크** | Gradio 6.11.0 (SSR 모드) |
| **LLM** | Fireworks AI → Kimi-K2.5 (`kimi-k2p5`) |
| **이미지 생성** | fal.ai → Grok Imagine (`xai/grok-imagine-image`) |
| **이미지 검증** | VLM (Kimi-K2.5 Vision) |
| **DB** | SQLite (WAL 모드) |
| **창작 엔진** | Emergence Seed JSON |

### 파이프라인 (4단계)
1. **Step 1** — 스토리 뼈대 생성 (LLM 1회)
2. **Step 2** — 페이지별 본문 생성 (LLM 15회, Beat Sheet 기반)
3. **Step 3** — 페이지별 삽화 생성 (fal.ai 15회) + VLM 품질 검증
4. **Step 4** — MARL 5-Agent 품질 검증 (LLM 1회)

## 인프라 상태

| 항목 | 상태 |
|------|------|
| HF Space | ✅ RUNNING (cpu-basic) |
| 빌드 | ✅ 전부 CACHED (~2초) |
| Gradio SSR | ✅ 정상 |
| SQLite WAL | ✅ 정상 |
| fal.ai 연동 | ✅ 정상 |
| Fireworks AI | ✅ 정상 (간헐적 reasoning 오염) |

## 런타임 로그 분석

### 동화 생성 세션 (15:23~15:39)
주제: **"우리 집에 온 꼬마 고양이"** — 15페이지

| 페이지 | 상태 | 비고 |
|--------|------|------|
| P1~P7 | ✅ 정상 | JSON 파싱 성공 |
| **P8** | ⚠️ 복구 | `Unterminated string` → 깨진 라인 제거로 복구 |
| **P9** | ⚠️ 복구 | `Extra data` → 괄호 복구 성공 |
| **P10** | ❌→✅ | JSON 실패 → reasoning 필터 + 재시도로 복구 |
| P11 | ✅ 정상 | |
| **P12** | ❌→✅ | 불완전 응답(87자) → 재시도 후 복구 |
| P13~P14 | ✅ 정상 | |

## 발견된 문제점

### 1. Kimi-K2.5 Reasoning 오염 (심각도: 높음)
- P9, P10에서 LLM이 JSON 대신 영어 reasoning 텍스트를 출력
- P10은 9630자 응답 중 대부분이 분석 텍스트 → JSON 파싱 완전 실패
- **영향**: 재시도로 인한 latency ~1분 추가, API 비용 2배

### 2. JSON 응답 잘림 (심각도: 중간)
- P8, P12에서 `Unterminated string` — `scene_description` 필드에서 잘림
- max_tokens=3000이 부족하거나 모델 출력 절단

### 3. 재시도 횟수 부족 (심각도: 낮음)
- `step2_generate_page_text`는 최대 2회 시도 — 여유 없음

## 개선 권장사항

1. **`response_format: {"type": "json_object"}`** API 파라미터 추가
2. **재시도 횟수** `range(2)` → `range(3)` 증가
3. **max_tokens** 3000 → 4000 증가
4. **temperature** high/climax 페이지에서 0.78 → 0.5 낮추기
5. **scene_description** 길이 제한 프롬프트에 명시

## 코드 품질 (양호)
- `safe_json_parse()`: 7단계 JSON 복구 로직이 견고
- DB 아키텍처: 페이지 단위 저장으로 부분 실패 대응
- VLM 검증 + 자동 재생성 파이프라인 잘 구성
- Emergence Seed 기반 창작 품질 파라미터 시스템

## 결론
Space는 정상 작동 중이며 동화 생성 파이프라인이 성공적으로 실행됨.
핵심 이슈는 Kimi-K2.5의 reasoning 오염으로, 15페이지 중 4페이지에서 JSON 파싱 문제 발생했으나
코드의 견고한 복구 로직으로 모두 해결됨. 추가 API 호출과 latency 비용 최적화가 권장됨.
