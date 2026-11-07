# 로컬 실행과 복구

이 MVP는 로컬 Docker Desktop Linux 엔진에서 실행한다. 외부 서비스에는 배포하지 않았다.
기본 로컬 모드는 로그인 화면을 생략하고 기존 demo 세션을 자동 시작한다.
`LOCAL_DEMO_MODE=false`면 명시 인증을 사용한다. production 설정은 자동 진입 모드를 거부한다.
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

Nginx는 Docker 내부 DNS로 API 주소를 주기적으로 갱신한다. API 컨테이너를 다시 생성해
IP가 바뀌어도 웹 컨테이너를 재시작할 필요가 없다. 설정은 Nginx 1.28의
[동적 upstream 주소 갱신](https://nginx.org/en/docs/http/ngx_http_upstream_module.html#server)을 사용한다.

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

## 사용 범위

로컬 전용 애플리케이션이며 외부 서버 배포와 인터넷 공개를 포함하지 않는다. Docker 포트는 localhost에만
바인딩한다. 사용자는 계정 생성·비밀번호 입력 없이 바로 작업공간을 사용한다.
명시 인증 코드는 소유권·세션 회귀검증용으로 보존하며, 기본 화면에는 로그인·로그아웃을 표시하지 않는다.
production 설정은 자동 demo 진입을 거부한다.

실행 provenance에는 설치 버전과 Python source SHA-256이 들어간다. `CODE_VERSION`에 실행 소스
커밋을 추가 지정할 수 있다. 코드/라이브러리가 달라진 오래된 queued run은 조용히 다른
환경으로 실행하지 않고 실패로 기록된다. 재현하려면 기록된 이미지/lock을 사용한다.

데이터 백업은 PostgreSQL native pg_dump/restore와 artifact 디렉터리를 함께 보존한다.
잠금 파일, 데이터 hash, 가중치 hash, validation report hash를 함께 추적한다.
