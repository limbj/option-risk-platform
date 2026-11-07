# 백엔드 실행·복구 설계

애플리케이션 DB는 PostgreSQL이다. `config.settings.test`의 메모리 SQLite는 빠른 HTTP·서비스 검사용이다. DB trigger와 동시성 증거는 `config.settings.postgres_test`로 PostgreSQL에서 별도로 확인한다.

## 입력과 소유권

`POST /api/inputs/`는 순수 `quant.inputs.parse_inputs` 검증 후 하나의 트랜잭션에서 PortfolioVersion, MarketSnapshot, ScenarioSetVersion, ModelVersion과 이를 묶는 InputVersion을 만든다. 날짜·enum·숫자·단위를 표준 JSON으로 정규화한 SHA256을 각 버전에 저장한다. 모든 입력과 실행에는 소유자가 있으며 목록, 상세, 생성 참조, 재시도, 다운로드에 소유권을 적용한다. 타인의 UUID는 404다.

발행된 버전·아티팩트·결과는 ORM 저장/갱신/삭제를 거부하고 Admin에서도 읽기 전용이다. PostgreSQL trigger는 raw SQL UPDATE/DELETE도 거부한다. 실행의 입력 ID·provenance는 생성 이후 바꿀 수 없고, 완료 실행과 완료 청크도 DB에서 변경을 거부한다. DB 관리자에게는 일반적으로 trigger 우회 권한이 있으므로 운영 DB 권한과 백업은 별도로 관리한다.

## 인증

Django 세션 인증과 CSRF를 사용한다. `GET /api/session/`이 로그인 상태와 CSRF 토큰을 반환한다. 익명 로그인 요청도 CSRF 검증을 통과해야 한다. 로그인 성공 시 세션/CSRF가 갱신된다. `/api/health/`는 공개 liveness이며 DB/Redis의 상태를 보장하지 않는다. 금융 API는 기본 인증 필수다.

로컬 데모 진입을 단순화하려면 development 설정에서 `LOCAL_DEMO_MODE=true`를 지정한다. 이때 익명 사용자의 `/api/session/` 호출은 `seed_demo`로 미리 준비한 active `demo` 계정의 일반 Django 세션을 자동으로 시작한다. 다른 사용자의 기존 세션은 바꾸지 않는다. 요청 파라미터로 계정을 선택하거나 새 계정을 만들 수 없으며 demo 계정이 없으면 준비 명령을 안내하는 503을 반환한다. 이후 금융 API의 세션·CSRF·소유권 검사는 그대로 적용된다. 응답의 `localDemoMode`는 프런트엔드의 로컬 작업공간 표시용이다. backend 기본값은 false이며 production 설정에서는 활성화를 거부한다. 이 모드를 사용하는 Compose 서비스는 localhost에만 공개한다.

## 실행과 outbox

`POST /api/runs/`는 소유자별 idempotency key를 사용한다. 같은 키와 같은 요청은 같은 실행을 반환하고 다른 요청은 409다. 실행·시나리오별 청크·outbox 이벤트를 같은 `transaction.atomic()`에서 만든 후 HTTP 202를 반환한다. 요청 경로는 계산하거나 Redis에 발행하지 않는다.

실행은 입력 버전 ID/hash, 평가일, Heston 수치 설정, 코드 SHA256/revision, 라이브러리 버전, 모델 artifact ID/manifest SHA256을 고정한다. 입력에 무충격 시나리오가 없으면 계산용 base를 추가하고 provenance에 기록하며 원본 입력은 유지한다.

`dispatch_outbox`는 짧은 발행 lease를 잡고 트랜잭션 밖에서 청크 ID만 Redis에 보낸다. 발행 성공 표시 전 프로세스가 죽으면 이벤트가 다시 발행될 수 있다. 이 중복은 정상 경로이며 worker가 처리한다. `transaction.on_commit()`에만 의존하지 않는다.

## 작업자와 복구

Celery는 Linux prefork 프로세스, late acknowledgment, worker-lost rejection, prefetch 1을 사용한다. 하나의 청크는 하나의 시나리오다. 실행 행과 청크 행을 같은 순서로 잠가 claim하고 임의 attempt token과 300초 lease를 발급한다. 계산은 DB 트랜잭션 밖에서 수행하며 QuantLib 어댑터가 평가일 상태를 관리한다.

결과 저장 시 현재 token과 유효 lease를 재검증한다. 만료된 작업자가 늦게 돌아와도 결과를 저장할 수 없다. 모든 셀의 결과 저장, 청크 종료와 실행 상태 갱신은 하나의 트랜잭션이다. `(run, scenario, position)` unique constraint로 이중 저장을 막는다. 저장 후 ACK를 잃어 중복 전달되면 이미 완료된 청크를 건너뛴다.

dispatcher는 만료 lease를 복구하고 발행 후 300초 동안 시작되지 않은 청크를 재발행한다. 계산 프로세스의 hard limit은 240초이며 lease보다 짧다. 최대 3회 작업자 유실 후 명시적인 실패 셀을 기록한다. DB 또는 Redis 중단 시 dispatcher가 운영 재시작 정책에 따라 다시 실행되어야 한다.

## 결과와 ML

가격/민감도 실패 셀은 `FAILED`와 오류 이유를 갖고 가격·가치는 null이다. 모든 필수 reference 셀이 성공한 시나리오에만 총액을 제공한다. P&L에는 완전한 base와 stress 총액이 모두 필요하다. 결과의 0은 실제 계산된 0이며 실패 대체값이 아니다.

COMPARE는 reference를 권위 있는 결과로 유지한다. ML 미지원 영역, 모델 사양 불일치, artifact 무결성 실패는 ML 오류 이유로 남고 reference를 보존한다. ML 총액과 P&L도 같은 ML 모델의 모든 필수 셀이 완전할 때만 제공한다. 단위당 base Delta/Gamma/initial-volatility sensitivity와 실제 bump를 함께 기록하며 초기 변동성 민감도는 decimal sigma0 1.0당이다.

새로운 재시도는 같은 입력·artifact를 참조하는 새 실행이다. 과거 결과를 덮어쓰지 않는다. JSON/CSV export는 입력·모델·코드 출처와 완전성 정보를 보존한다. CSV의 사용자 입력 이름은 수식 실행을 방지하도록 escape한다.

## 운영 명령

```text
python manage.py migrate
python manage.py seed_demo --username demo
python manage.py register_artifact --directory artifacts/demo
celery -A config.celery:app worker --pool=prefork --concurrency=2
python manage.py dispatch_outbox
python manage.py recover_work
pytest tests/django --ds=config.settings.postgres_test
```

`seed_demo`는 환경변수 `DEMO_PASSWORD`를 요구하며 기존 비밀번호를 덮어쓰지 않는다. artifact 등록은 운영자 CLI에서만 가능하고 `ARTIFACT_ROOT` 아래 경로와 manifest/weights/report hash를 검증한다. 검증된 세 파일은 `registered/<manifest SHA256>/`에 따로 보관하여 오프라인 학습 출력 경로를 재사용해도 과거 모델 바이트를 보존한다. 같은 hash의 보관 디렉터리는 덮어쓰지 않고 무결성을 다시 검사한다. 같은 hash/path 재등록은 기존 ID를 반환한다. worker에는 artifact 볼륨을 읽기 전용으로 마운트한다. API 사용자가 파일 경로나 실행 가능한 모델을 업로드할 수 없다.

`config.settings.production`은 명시적인 호스트와 50자 이상 secret, HTTPS/secure cookie를 요구한다. `DJANGO_TRUST_PROXY=true`는 전달 헤더를 제거·재설정하는 신뢰할 수 있는 HTTPS reverse proxy에서만 사용한다. 일반 로컬 Compose는 development 설정을 사용한다. 비편집 wheel 설치 시 프로젝트 리소스 위치는 `PROJECT_ROOT`로 지정할 수 있다.
