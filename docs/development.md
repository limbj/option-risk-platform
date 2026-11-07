# 개발과 재현

먼저 [README의 로컬 실행](../README.md#로컬-실행)으로 DB·데모 입력·모델·컨테이너를 준비한다.
Python 의존성은 `uv.lock`, 프런트엔드 의존성은 `frontend/package-lock.json`으로 고정한다.
아래 `uv`는 Windows의 `.\work\bootstrap\Scripts\uv.exe`로 대체할 수 있다.

## Python 검사

```powershell
uv sync --locked --extra ml
uv run --locked --extra ml pytest
uv run --locked --extra ml ruff check .
uv run --locked --extra ml ruff format --check .
uv run --locked --extra ml python manage.py check --settings=config.settings.test
uv run --locked --extra ml python manage.py makemigrations --check --dry-run --settings=config.settings.test
```

기본 pytest는 빠른 Django 검사에 SQLite 메모리 DB를 사용한다. PostgreSQL 전용 검사는
해당 환경에서 skip되므로 실제 DB의 trigger·동시성·복구 검사를 별도로 실행한다.

```powershell
docker compose up -d --wait db redis
uv run --locked --extra ml --env-file .env pytest --ds=config.settings.postgres_test tests/django
docker compose --profile test run --rm tests
docker compose --profile test run --rm postgres-tests
```

PostgreSQL 검사는 별도 테스트 DB를 생성·정리한다. 같은 테스트 DB에 두 검사를 동시에 실행하지 않는다.
`tests`와 `postgres-tests`는 검사가 끝나면 종료되는 일회성 컨테이너다.

## 프런트엔드 개발

호스트 개발에는 Node 24를 사용한다. Docker 웹과 Vite가 같은 5173 포트를 사용하므로
Docker 웹만 중지한 뒤 개발 서버를 실행한다. Vite는 `/api`를 localhost:8000으로 전달한다.

```powershell
docker compose stop web
cd frontend
npm ci
npm test
npm run build
npm run dev
```

Vite를 종료하고 저장소 루트에서 `docker compose up -d web`을 실행하면 Docker 웹으로 돌아간다.
프런트엔드 변경을 Docker 이미지에 반영하려면 `docker compose up -d --build web`을 사용한다.

## 백엔드 변경 반영

API·worker·dispatcher는 같은 이미지를 사용한다. 코드가 변경되면 세 서비스를 함께 갱신한다.

```powershell
docker compose build api
docker compose up -d --no-deps api worker dispatcher
```

필요한 마이그레이션은 새 이미지로 적용한다.

```powershell
docker compose exec api python manage.py migrate
```

HTTP 개발 서버를 호스트에서 직접 띄우려면 Docker API를 중지한 뒤 실행한다.

```powershell
docker compose stop api
uv run --locked --extra ml --env-file .env python manage.py runserver
```

평가 실행은 API와 worker의 코드·라이브러리 버전이 일치해야 한다. 호스트와 컨테이너의
환경이 다른 상태에서 제출한 실행은 출처 검증에 실패할 수 있으므로 전체 계산 검증에는 Compose를 사용한다.

## 브라우저와 실제 서비스 검사

웹·API·worker·dispatcher가 준비된 상태에서 다음을 실행한다.

```powershell
cd frontend
npx playwright install chromium
node --env-file=../.env node_modules/@playwright/test/cli.js test
```

기본 `.env`의 `LOCAL_DEMO_MODE=true`에서는 자동 진입 흐름을 검사한다.
명시적인 로그인 흐름을 확인할 때는 `.env`의 값을 false로 바꾸고 API를 다시 생성한다.
이 경우 테스트는 `.env`의 `DEMO_PASSWORD`를 사용하며 비밀번호를 명령행에 직접 입력하지 않는다.

실제 HTTP·CSRF·소유권·큐 검사는 저장소 루트에서 실행한다.

```powershell
uv run --locked --extra ml --env-file .env python scripts/verify_stack.py
```

복구 검사는 이 프로젝트의 dispatcher 또는 worker를 일시 중단하므로 다른 계산이 없는 로컬 환경에서 실행한다.
동작과 증거 형식은 [실제 실행·복구 기록](stack-validation.md)에 설명되어 있다.

```powershell
uv run --locked --extra ml --env-file .env python scripts/verify_stack.py --recovery-dispatcher
uv run --locked --extra ml --env-file .env python scripts/verify_worker_recovery.py --timeout 420
```

## 모델과 로컬 데이터

학습·평가를 다시 실행하는 명령과 품질 기준은 [ML 검증 보고서](ml-validation.md)에 있다.
새 모델은 기존 경로를 덮어쓰지 않고 새 디렉터리에 생성한 뒤 등록한다.
등록된 파일은 manifest 해시별 보관 경로에 복사되며 worker는 읽기 전용으로 사용한다.

`.env`, DB 파일, 데이터셋, 가중치, `work/`는 Git에서 제외한다.
bootstrap은 기존 `.env`와 DB를 유지하며 초기 생성한 비밀값을 출력하지 않는다.
`docker compose stop`과 `docker compose down`은 DB 볼륨을 보존한다.

## 상태와 로그

```powershell
docker compose ps
docker compose logs --tail 50 api worker dispatcher
```

서비스별 포트와 복구 명령은 [로컬 운영 가이드](deployment.md),
원격 검사 순서와 보고서는 [CI 검증](ci-validation.md)을 참고한다.
