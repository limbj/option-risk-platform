# Option Risk Platform

고정된 입력·모델로 옵션 포트폴리오를 평가하고, 스트레스 손익과 Heston/ML 가격을 비교하는
Django 기반 연구용 MVP입니다. 합성 지수 `SYNTH_INDEX`, USD, 무배당 유럽형 현금결제
콜/풋과 ACT/365F를 지원합니다. 실패는 0으로 바꾸지 않으며 완결된 결과만 합산합니다.

## 로컬 데모

필수: Docker Desktop의 Linux 엔진, Python, uv **0.13.7**.
애플리케이션 Python **3.12**는 uv가 관리합니다.

```powershell
# Windows에서 uv가 없는 경우, 저장소 전용 설치
python -m venv work/bootstrap
.\work\bootstrap\Scripts\python.exe -m pip install uv==0.13.7
# DB 초기화, 비밀키 생성, ML 학습·검증, 이미지 빌드와 서비스 시작
python scripts/bootstrap_demo.py
```

**http://127.0.0.1:5173** → 사용자 `demo`, 비밀번호는 생성된 `.env`의 `DEMO_PASSWORD`입니다.
기존 `.env`를 사용한다면 비밀번호를 12자 이상으로 설정하세요. 기존 DB·산출물은 삭제하지 않습니다.
비밀키·DB·데이터셋·가중치는 Git에서 제외됩니다.

포지션 수동/CSV 입력 → 시장·시나리오 설정 → 입력 버전 저장 → REFERENCE/COMPARE 실행
→ 실행 이력·결과·민감도·히트맵·CSV/JSON 확인의 흐름입니다. ML은 비교용이며 공식 가격과
민감도는 QuantLib AnalyticHestonEngine을 사용합니다. 지원 영역 밖의 ML 입력은 이유를 기록합니다.

```powershell
docker compose ps
docker compose logs --tail 50 worker dispatcher
docker compose stop
docker compose up -d db redis api worker dispatcher web
```

Gunicorn/Nginx/PostgreSQL/Redis/Linux prefork Celery worker와 outbox dispatcher를 실행합니다.
`tests` 컨테이너는 테스트 종료 후 정상 종료되는 일회성 작업입니다.

## 개발과 검증

아래 `uv`는 `.\work\bootstrap\Scripts\uv.exe`로도 실행 가능합니다.
`uv.lock`과 `frontend/package-lock.json`으로 직접·간접 의존성을 고정합니다.

```powershell
uv sync --locked --extra ml
uv run --locked --extra ml pytest
uv run --locked --extra ml ruff check .
uv run --locked --extra ml ruff format --check .
uv run --locked --extra ml python manage.py check --settings=config.settings.test
uv run --locked --extra ml python manage.py makemigrations --check --dry-run --settings=config.settings.test
uv run --locked --extra ml --env-file .env pytest --ds=config.settings.postgres_test tests/django
docker compose --profile test run --rm tests
docker compose --profile test run --rm postgres-tests
uv run --locked --extra ml --env-file .env python scripts/verify_stack.py

cd frontend
npm ci
npm test
npm run build
npx playwright install chromium
node --env-file=../.env node_modules/@playwright/test/cli.js test
npm run dev
```

호스트 프론트 개발은 Node 24를 사용하며 Vite가 `/api`를 localhost:8000으로 전달합니다.
Django 호스트 실행: `uv run --locked --extra ml --env-file .env python manage.py runserver`.
SQLite 메모리 DB는 빠른 테스트 전용이고 PostgreSQL trigger·동시성·복구는 별도로 검증합니다.

## 구조와 기록

- `src/config`, `src/apps`: Django/DRF, 세션·CSRF·소유권, 불변 ORM 버전, 실행·outbox·복구
- `src/quant`: 독립 금융 계약, Black–Scholes, Heston, 민감도, 스트레스, 완결성 집계
- `src/ml`: 독립 teacher 데이터·학습·검증·manifest·추론
- `frontend`: React/TypeScript/Vite, TanStack Query, Plotly
- `tests`, `scripts`, `examples`: 검증, 재현 데모, 합성 입력
- `docs/PROGRESS.md`: 완료·검증·미해결·다음 작업
- `docs/financial-contracts.md`, `docs/numerical-validation.md`: 금융 단위·수치 검증
- `docs/backend-design.md`, `docs/review-findings.md`: 영속성·복구·독립 검토
- `docs/ml-validation.md`, `docs/stack-validation.md`: 실제 학습 및 통합 측정
- `docs/deployment.md`: 배포 준비·운영 절차

실행과 outbox를 같은 트랜잭션에 저장하고 큐에는 ID만 전달합니다. 고정된 입력과 해시를
재검증하고 lease/attempt token으로 중복·지연 결과를 차단합니다. 전체 설계는
`PROJECT_BRIEF.txt`를 참고하세요. 외부 배포는 별도 승인 대상입니다.

기술 근거: [Django](https://www.djangoproject.com/download/),
[DRF](https://www.django-rest-framework.org/),
[uv lock](https://docs.astral.sh/uv/concepts/projects/sync/),
[uv Docker](https://docs.astral.sh/uv/guides/integration/docker/).
