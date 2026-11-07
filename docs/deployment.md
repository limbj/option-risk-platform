# 실행·배포 준비와 운영

이 MVP는 로컬 Docker Desktop Linux 엔진에서 실행한다. 외부 서비스에는 배포하지 않았다.
`scripts/bootstrap_demo.py`가 `.env`를 생성하고 DB/migration/데모 계정/학습 모델/이미지를 준비한다.
초기 데이터와 모델은 다시 생성할 수 있으며 실제 시장 데이터가 아니다.

## 서비스와 포트

| 서비스 | 역할 | 호스트 노출 |
|---|---|---|
| web | Nginx 정적 React + 같은 origin API proxy | 127.0.0.1:5173 |
| api | Gunicorn/Django HTTP | 127.0.0.1:8000 |
| db | PostgreSQL 영속 입력·실행·outbox·결과 | 127.0.0.1:5432 |
| redis | Celery 메시지 운반 | 127.0.0.1:6379 |
| worker | Linux prefork, 2 process | 없음 |
| dispatcher | outbox 전송·lease 만료 복구 루프 | 없음 |
| tests, postgres-tests | 종료형 검증 작업 | 없음 |

API·워커는 같은 소스를 담은 이미지와 읽기 전용 `artifacts/`를 사용한다.
GPU 없이 CPU PyTorch를 사용한다. 데이터 볼륨을 유지하려면 `docker compose stop` 또는
`docker compose down`을 사용하고 `down -v`는 데이터 삭제를 의도한 경우에만 실행한다.

## 복구

- Run 생성은 DB에 입력 ID/hash/모델·코드·수치 설정과 outbox를 함께 저장한다.
- dispatcher가 중단되면 run은 QUEUED로 남는다. 재시작하면 미전송 outbox가 다시 발행된다.
- publish 직후 dispatcher가 종료되어도 재발행을 허용하고 worker가 중복 처리를 차단한다.
- 워커가 claim 후 종료되면 lease 만료 후 dispatcher가 복구한다. 기본 lease 300초,
  task hard limit 240초이며 복구는 즉시 재실행과 구별된다.
- 실행 token이 바뀐 이전 워커의 결과는 저장하지 않는다. 최종 결과 저장 후 재전달은 no-op다.
- 참조 가격 실패와 ML 지원 불가 이유를 보존한다. 부분 실패 실행은 새 run으로 재실행한다.

```powershell
docker compose logs --tail 100 api worker dispatcher
docker compose exec api python manage.py dispatch_outbox --once
docker compose exec api python manage.py recover_work
```

실제 recovery command 이름/옵션은 `python manage.py help`로 확인할 수 있다.
결과 수정 대신 동일 입력으로 새 실행을 만든다. 모델 파일은 기존 버전 경로에 덮어쓰지 않고
새 경로에서 검증한 뒤 `register_artifact` 명령으로 새 버전을 등록한다.

## 외부 배포 시 적용할 설정

외부 배포는 별도 지시가 필요하다. 배포 대상에서는 TLS 종료 proxy와 private DB/Redis,
비밀 저장소, 백업·복원·모니터링을 운영자가 구성한다. 로컬 `.env`의 데모 비밀번호는 배포에 사용하지 않는다.

`DJANGO_SETTINGS_MODULE=config.settings.production`, 50자 이상의 랜덤 `DJANGO_SECRET_KEY`,
명시한 `DJANGO_ALLOWED_HOSTS`, HTTPS `DJANGO_CSRF_TRUSTED_ORIGINS`를 지정한다.
secure cookie/HTTPS redirect/HSTS가 적용된다. 신뢰하는 proxy가 외부 forwarded header를
제거하는 경우에만 `DJANGO_TRUST_PROXY=true`를 설정한다. POST 요청의 CSRF를 우회하지 않는다.

```powershell
uv run --locked --extra ml --env-file .env python manage.py check --deploy --settings=config.settings.production
```

실행 provenance에는 설치 버전과 Python source SHA-256이 들어간다. `CODE_VERSION`을 배포
커밋으로 추가 지정할 수 있다. 코드/라이브러리가 달라진 오래된 queued run은 조용히 다른
환경으로 실행하지 않고 실패로 기록된다. 재현하려면 기록된 이미지/lock을 사용한다.

데이터 백업은 PostgreSQL native pg_dump/restore와 artifact 디렉터리를 함께 보존한다.
잠금 파일, 데이터 hash, 가중치 hash, validation report hash를 함께 추적한다.
