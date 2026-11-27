# 노지각 — 더 이상 지각은 없다

지도 앱이 출발 시각을 알려준다면, 노지각은 실제로 출발할 수 있도록 준비 행동과 전환을 관리하는 모바일 우선 AI 코치입니다.

## 실행 방법

### 프런트엔드

Node.js 20.19 이상(또는 22.12 이상)과 npm이 필요합니다.

```bash
npm install
npm run dev
```

브라우저에서 Vite가 안내하는 주소(기본 `http://localhost:5173`)를 엽니다. 프로덕션 빌드는 `npm run build`, 미리보기는 `npm run preview`를 사용합니다.

### 백엔드

Python 3.10 이상이 필요합니다.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

저장소 루트에서 예시 환경파일을 복사하고 키를 채운 뒤, 저장소 루트에서 다음을 실행합니다.

```bash
cp .env.example .env
# .env에 필요한 키를 입력한 후 현재 셸에 불러옵니다.
set -a && source .env && set +a
uvicorn backend.app.main:app --reload --port 8000
```

프런트 개발 서버는 `/api` 요청을 `localhost:8000`으로 전달합니다. API 키 없이도 수동 이동시간 입력으로 일정 생성, 타이머, 기록과 습관 분석을 사용할 수 있습니다.

## 환경변수

백엔드 프로세스 환경변수로 설정합니다. 키를 프런트엔드 코드나 `VITE_*` 변수에 넣지 마세요.

| 변수 | 용도 |
| --- | --- |
| `KAKAO_REST_API_KEY` | Kakao Local 장소 검색 및 주소 좌표 변환 |
| `ODSAY_API_KEY` | ODsay 대중교통 경로 소요시간 조회 |
| `FRONTEND_ORIGINS` | 백엔드 CORS 허용 프런트엔드 origin (쉼표 구분) |

장소/경로 API가 설정되지 않거나 실패하면 검색 실패 안내를 제공하고, 사용자가 직접 이동시간을 입력해 핵심 기능을 계속 사용할 수 있습니다. 조회된 경로 시간도 실시간 교통정보가 아닙니다.

## 개인화 이동시간 백엔드 API

FastAPI의 Swagger 화면(`http://localhost:8000/docs`)에서 아래 API를 호출할 수 있습니다. 기록은 서버에 저장되지 않습니다. 개인화 예측에 쓸 때마다 요청의 `history`에 유효한 이동기록을 전달해야 하며, 같은 요청 안에서는 `id`와 `run_id` 중복을 제거합니다. 별도 기록 저장소나 프런트엔드 연동은 포함하지 않았습니다.

`/api/route`는 기존 `duration_minutes`, `source`, `transfers`, `fare`, `realtime`을 유지하고 `route_key`, `fetched_at`, `prediction_source`를 추가로 반환합니다. ODsay 응답에 `info.mapObj`가 있으면 `route_signature`로 전달하고 route key에 포함합니다. 이는 경로 그래픽용 서명으로 취급하며, 제공자 route ID라고 단정하지 않습니다. 서명이 없으면 약 100m 단위로 정규화한 양 끝 좌표 기반 route group을 사용합니다. [ODsay 공식 가이드 예시는 `info.mapObj`를 노선 그래픽 API 입력으로 사용합니다.](https://lab.odsay.com/guide/guide?platform=web)

### 예측 및 통합 시간표

```bash
curl -X POST http://localhost:8000/api/travel/predict \
  -H 'Content-Type: application/json' \
  -d '{"route_key":"sample-route","base_travel_minutes":70,"prediction_source":"api","strategy":"balanced","history":[]}'

curl -X POST http://localhost:8000/api/travel/plan \
  -H 'Content-Type: application/json' \
  -d '{"route_key":"sample-route","base_travel_minutes":70,"prediction_source":"api","strategy":"balanced","history":[],"target_arrival_at":"2026-11-30T09:00:00+09:00","routine_minutes":65,"transition_minutes":5,"reserve_minutes":5,"arrival_buffer_minutes":5,"extra_travel_buffer_minutes":0}'
```

`efficient`, `balanced`, `safe` 전략의 비교값도 `/api/travel/predict` 응답에 포함됩니다. cold start의 교통 여유는 각각 5·10·20분입니다. 추천 출발 이동량은 `updated - previous` 부호이며 음수는 더 일찍 출발, 양수는 더 늦게 출발을 뜻합니다. 개인화 전략 여유는 `effective_travel_minutes`에 이미 포함되므로 별도 여유를 입력할 때 중복되지 않게 합니다.

기본 예측은 `is_demo=true` 기록을 계속 제외합니다. 시연 전용 fixture 계산만 `demo_context: true`를 요청해 데모 표시가 붙은 기록을 일회성 stateless 계산에 포함할 수 있으며, 완료 기록 API와 영속 학습 정책에는 이 컨텍스트가 적용되지 않습니다.

### 완료기록 및 분석

```bash
curl -X POST http://localhost:8000/api/travel/complete \
  -H 'Content-Type: application/json' \
  -d '{"id":"trip-1","run_id":"run-1","route_key":"sample-route","target_arrival_at":"2026-11-30T09:00:00+09:00","recommended_departure_at":"2026-11-30T07:25:00+09:00","actual_departure_at":"2026-11-30T07:25:00+09:00","actual_arrival_at":"2026-11-30T08:53:00+09:00","api_travel_minutes":70,"predicted_travel_minutes":72,"effective_travel_minutes":82,"prediction_source":"api","strategy":"balanced","abnormal":false,"is_demo":false}'

curl -X POST http://localhost:8000/api/travel/metrics \
  -H 'Content-Type: application/json' \
  -d '{"route_key":"sample-route","records":[]}'
```

`/api/travel/complete`은 시간 차이를 서버에서 계산합니다. `abnormal`, `is_demo`, 경유 기록, 수동 예측은 residual 학습에서 제외합니다. 중복 실행 방지는 전달된 history 목록 안에서 적용되며, stateless API는 이전 요청의 run ID를 기억하지 않습니다. 비정상·데모 기록은 API 요청의 데이터를 직접 수정하지 않습니다.

가상 수도권 통학 시나리오를 실제 계산 함수로 재생하려면 저장소 루트에서 `backend/.venv/bin/python backend/demo_travel.py`를 실행합니다. 가상 기록은 프로세스 메모리에서만 사용하며 결과를 저장하지 않습니다. 기존 React 화면은 이 신규 API를 호출하지 않습니다.

## 구현된 기능

- 반응형 홈, 일정/실행 화면, 습관 분석 화면과 하단 내비게이션
- 신규 사용자를 위한 시간 감각 자기진단과 루틴별 자기보고 예상시간의 cold-start 반영 (수행기록/EWMA와 분리)
- 일정 이름, 반복 요일, 출발 모드와 루틴별 설정을 브라우저에 저장하고, 저장된 템플릿에서 개인 기록으로 시간표를 새로 계산
- 기본 현재 위치 조회와 주소 직접 입력 fallback, 위도/경도 출발점 경로 조회 (좌표는 템플릿에 저장하지 않음)
- 목적지·도착시간 중심의 3단계 일정 작성, 상세 루틴 설정 접기, 내비게이션을 숨기는 준비 집중 모드
- SpeechSynthesis 한국어 음성 코칭 설정과 중복 이벤트 억제; 미지원 시 시각 안내 유지
- 준비 시작 지연과 루틴 간 전환시간 별도 기록, 시작 전 5분 알림, 원터치 완료 후 다음 루틴 시작
- 정상 완료된 전환 기록 5회부터 EWMA 전환시간을 계획/재분배 시간에 포함하고, 유효 표본이 적으면 확률 대신 Slack 위험을 표시
- 실행 화면의 출발 마감 카운트다운, 재분배 이유/예비시간/루틴 변경/예상 준비 완료/다음 행동 카드
- 개인 저장 데이터를 바꾸지 않는 인터랙티브 데모와 실제 재분배·개인화 함수 실행
- 홈의 `가상 시나리오 시작 — 78초 체험` 버튼으로 실행하는 자동 녹화용 데모; 가상 준비 기록은 `predictDuration()`/`initialAllocations()`로, 이동·출발 계획은 stateless `/api/travel/plan`으로 계산하고, 도착 후 가상 기록을 포함한 다음 계획을 다시 계산합니다. 화면의 GPS·경로·도착은 모두 시뮬레이션이며 개인 `localStorage`나 완료기록 API에 저장되지 않습니다.
- 자기 예상/루틴 합계, 실제 평균, 시작 지연, 행동 전환, 주요 초과 루틴, 다음 일정 예상시간의 교정 리포트
- 도착 시각에서 이동시간, 교통 여유, 도착 여유를 빼 출발 마감 계산
- 기본 준비 루틴, 루틴 추가·이름/시간 수정·삭제·순서 변경
- 루틴 시작/완료를 사용자가 직접 제어하는 카운트다운과 초과시간 표시
- 시작 후 브라우저 새로고침에도 복구되는 실행 타임스탬프와 진행 상태
- 준비 진행률, 루틴별 실행 가이드, 중간/마무리/시간 초과 개입 알림
- 완료·건너뛰기 기록과 비정상 기록 제외 기능
- EWMA(α=0.25), 기록 10회부터 최근 최대 20개 Q80, cold-start 가중치 `n/(n+8)`를 적용한 다음 일정 시간 예측
- 최근 실제/계획 시간 그래프, 루틴별 학습 시간과 시간 내 완료율
- Kakao Local 장소 검색 및 ODsay 경로 시간 API를 호출하는 FastAPI 백엔드 프록시
- 브라우저 오프라인 학습과 동일한 계산을 제공하는 FastAPI/NumPy `/api/personalize` 엔드포인트
- 일정, 루틴, 설정, 실행상태, 개인화 기록은 브라우저 `localStorage`에 저장

## 적응형 스케줄링 확장

- 일정/루틴에 유형, 중요도, 최소 소요시간, 단축 유연성, 선택 생략 허용 설정을 추가했습니다. 이전 `localStorage` 루틴은 읽을 때 기본값을 채워 마이그레이션합니다.
- 실행 중 지연이 생기면 남은 준비시간을 출발 마감과 비교해 예비시간을 먼저 사용하고, 사용자가 허용한 범위 안에서 낮은 중요도·높은 유연성 루틴부터 줄입니다. 끝내지 못한 부족분은 지연으로 표시합니다.
- 조기 완료 후에는 미리 줄였던 시간을 먼저 복원하고, 남는 시간은 예비시간으로 확보합니다. 완료 기록과 최초 배분은 변경하지 않으며, 최초/현재 배분과 재계산 이력은 실행 상태에 보존됩니다.
- 실행 중인 루틴의 남은 시간은 현재 경과시간보다 긴 과거 수행기록의 조건부 잔여시간으로 추정합니다. 적절한 기록이 없으면 보수적 임시 추정과 사용자 입력을 제공합니다.
- Slack은 5분 이상 안전, 0~5분 주의, 음수 위험으로 표시합니다. 미완료 루틴마다 정상 기록이 10회 이상일 때만 최근 최대 20개 실제시간 분포를 이용해 1,000회 시뮬레이션 확률을 표시합니다. 부족한 데이터에는 확률 대신 Slack 상태를 표시합니다.
- 긴급 플랜은 변경·생략 대상을 먼저 비교하고 사용자가 적용을 눌러야 반영합니다. 필수 루틴과 최소시간은 지키며, 선택 루틴 생략을 동의 없이 처리하지 않습니다.
- 정상, 시간 압축, 긴급 수행을 분리해 시간 압축 및 긴급 기록은 기본 EWMA/Q80 학습에서 제외합니다.
- 반복 지연 원인과 최초 배분 대비 누적 초과시간 비중을 표시하고, 이를 실제 지각의 인과 원인으로 표현하지 않습니다.
- 등교/출근, 일반 약속, 중요한 일정, 기타 유형별 개인화를 적용합니다. 상황별 정상 기록이 5회 미만이면 전체 모델을 사용하고, 5회부터 두 모델을 가중 혼합합니다.
- 기록 기반 병목이 옷 고르기 또는 짐 챙기기에서 반복되면 전날 준비 체크리스트를 제안합니다. 체크리스트는 사용자가 완료 표시하기 전까지 유지되고 아침 루틴을 자동 생략하지 않습니다.
- 독립 적응형 계산 테스트: `node --test src/adaptive.test.mjs` (20개 시나리오 통과).
- Node 환경에서는 같은 테스트를 `npm test`로도 실행할 수 있습니다.

## 데이터 계산 메모

개인 기록 학습은 각 루틴에 유효한 완료 기록만 반영합니다. 처음 유효한 기록으로 EWMA를 초기화하고, 이후 기록에 α=0.25를 적용합니다. 유효 기록 10회 이상은 최근 20개(또는 그 이하)의 Q80과 EWMA 중 큰 값을 개인 학습값으로 사용합니다. 기본시간과 학습값은 `n/(n+8)` 비율로 섞고, 분 단위로 올림합니다. 건너뛴 기록과 사용자가 학습 제외한 기록은 통계에서 제외됩니다.

## 검증 결과 및 제한사항

- `npm test`: 적응형 엔진 회귀 시나리오 20개 통과.
- `npm run build`: TypeScript 검사와 Vite 프로덕션 빌드 성공. 현재 단일 번들이 500 kB 경고 기준을 넘습니다.
- `python3 -m compileall -q backend/app`: 백엔드 문법 컴파일 성공. `backend/.venv`의 FastAPI TestClient mock으로 health, 기존 문자열 출발지 호환, 좌표 경로 요청, 좌표 범위/쌍 검증을 확인했습니다. 외부 Kakao/ODsay 실제 호출은 API 키가 없어 검증하지 않았습니다.
- 브라우저에서 375px/390px 레이아웃(가로 넘침 없음), 홈, 일정 생성 1단계, 데모 재분배, 설정 화면을 확인했습니다. 브라우저 위치 권한은 요청하지 않았고, 실제 ODsay/Kakao 호출은 API 키가 없어 mock 검증으로 대체했습니다.
- 브라우저 알림과 음성 안내는 앱이 열린 동안에만 동작하며 브라우저/운영체제 상태에 따라 전달이 보장되지 않습니다.
- ODsay 경로 조회는 Kakao 목적지 좌표 변환과 ODsay API 키가 필요합니다. API 키, 쿼터, 네트워크 상태에 따라 실패할 수 있으며 수동 이동시간 입력이 대체 수단입니다.
- 정보는 현재 브라우저의 `localStorage`에만 저장되므로 다른 기기와 동기화되지 않습니다. 인증/계정 서버는 포함하지 않습니다.
