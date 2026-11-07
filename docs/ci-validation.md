# MVP CI 검증 구성

`.github/workflows/ci.yml`의 `MVP acceptance`는 push, pull request, 수동 실행에서
단일 Ubuntu job을 수행한다.

2026-11-08 01:58(KST), commit `bb0d2c36a1f1e930e07c7ed7344c516034a63f0c`의
[GitHub Actions 실행 42393470972](https://github.com/limbj/option-risk-platform/actions/runs/42393470972)이
**성공**했다. 전체 job 소요 시간은 5분 37초였다.

| 검사 | 원격 결과 |
| --- | --- |
| Host 전체 pytest | 443 passed, 4 PostgreSQL 전용 skipped |
| Host PostgreSQL | 66 passed |
| Linux 이미지 전체 pytest | 443 passed, 4 PostgreSQL 전용 skipped |
| Linux 이미지 PostgreSQL | 66 passed |
| Frontend 단위 테스트 / build | 7 passed / 성공 |
| 실제 16,000 표본·350 epochs 학습 및 품질 gate | 성공 |
| HTTP·인증·소유권·큐·dispatcher 복구 | 19개 검사, 6개 실행 통과 |
| Playwright 브라우저·모바일 workflow | 1 passed |

JUnit·로그·ML 검증 report·UI 스크린샷은
[실행 증거 artifact](https://github.com/limbj/option-risk-platform/actions/runs/42393470972/artifacts/13583035641)에
보존된다(14일 보존 정책).

## 실행 순서

1. uv 0.13.7, Python 3.12, Node 24를 설치하고 `uv.lock` 및
   `frontend/package-lock.json`으로 의존성을 설치한다. ML extra도 포함한다.
2. Ruff 검사·포맷, 전체 pytest, Django 시스템 검사와 migration drift 검사를 수행한다.
   이 첫 pytest는 SQLite 프로필이므로 PostgreSQL 전용 검증은 skip으로 기록된다.
3. 프론트 단위 테스트·TypeScript/Vite build를 수행하고 Chromium을 준비한다.
4. Compose PostgreSQL/Redis를 시작하고 PostgreSQL 프로필의 Django 테스트를 수행한다.
   실제 row lock, 불변성 trigger, 완료 상태와 INSERT 경합, outbox·worker 복구가 포함된다.
5. app와 web 이미지를 각각 한 번 build한다. 같은 app 이미지를 재사용하여 Linux
   전체 pytest와 PostgreSQL Django 테스트를 실행한다. API·worker·dispatcher도
   이 이미지로 실행하므로 서비스별로 반복 build하지 않는다.
6. 16,000개 학습 표본, 350 epochs로 새 CPU baseline을 생성하고, 고정된
   `docs/ml-demo-gates.json`으로 평가한다. 평가 CLI가 report를 만든 뒤에도
   manifest의 `validation.status == passed`를 별도로 강제하여 gate 실패는 CI 실패가 된다.
7. migration을 적용하고 소유자가 다른 테스트 계정 두 개를 생성한다. 평가를 마친
   `artifacts/demo`만 등록하여 브라우저 테스트에 필요한 artifact 한 개를 유지한다.
8. API·Linux prefork worker·dispatcher·Nginx 웹을 시작한다. 실제 HTTP를 통해
   인증·CSRF·소유권·입력 검증·가격·민감도·비교·export·재실행을 검사하며,
   dispatcher 중단 중 생성한 작업이 재시작 후 처리되는지 확인한다.
9. Playwright로 로그인부터 CSV 입력, REFERENCE/COMPARE, 다운로드, 히트맵,
   모바일 레이아웃까지 확인한다.

## 증거와 실행 환경

Host pytest JUnit, PostgreSQL JUnit, 컨테이너 테스트 로그, stack JSON report,
학습·gate 로그, validation report와 manifest, UI 스크린샷 및 실패 trace를
Actions artifact로 14일 보존한다. 실패 시에도 container 상태·로그를 수집한다.
데이터셋·모델 가중치·`.env`는 업로드하지 않는다.

CI의 DB·Django·계정 값은 disposable runner 전용 상수다. 운영 비밀값이나 GitHub
repository secrets를 사용하지 않는다. Compose는 기존 로컬 `.env`를 만드는 bootstrap
스크립트 대신 job 환경변수를 사용한다. 실행 마지막에는 runner의 컨테이너와 볼륨을
정리한다. 이미지 push나 외부 배포는 수행하지 않는다.

로컬 체험의 자동 진입과 인증 검증을 구분하기 위해 CI는 `LOCAL_DEMO_MODE=false`를
명시한다. 실제 로그인·CSRF·소유자 격리는 이 인증 모드에서 계속 검증한다.

전체 job은 35분 제한이며 같은 branch/ref의 이전 실행은 새 실행으로 교체한다.
정확도 gate는 필수이고 속도향상은 보고 항목이다. OS/CPU가 바뀌면 측정 시간과
학습 부동소수점 결과가 달라질 수 있으므로 기존 가중치를 성공 증거로 재사용하지 않는다.

## 구성 검증

workflow YAML 파싱, job/step 구조, 필요한 검사 명령과 artifact 수집 경로를 확인했다.
개별 애플리케이션의 로컬 검증 결과는 `numerical-validation.md`, `ml-validation.md`,
`stack-validation.md`에서 관리한다.
서비스 readiness 검사는 일시적 연결 reset도 재시도하며, 전체 120초·연결 2초·개별 요청
10초 상한을 둔다. 지속적인 서비스 오류는 시간 제한 후 CI 실패로 남긴다.

현재 action 입력과 Node 실행 방식은 공식
[checkout](https://github.com/actions/checkout),
[setup-node](https://github.com/actions/setup-node),
[setup-uv](https://github.com/astral-sh/setup-uv),
[upload-artifact](https://github.com/actions/upload-artifact) 문서를 확인했다.
