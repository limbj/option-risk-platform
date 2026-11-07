# 서비스 통합·복구 검증

`scripts/verify_stack.py`는 실행 중인 Docker 서비스의 HTTP API를 호출해 PostgreSQL 입력·실행,
outbox, Redis, Celery worker와 ML artifact를 거친 결과를 검사한다. Python 표준 라이브러리만 사용한다.

## 실행

API·worker·dispatcher가 기동되어 있고 migration·demo 계정·ML artifact 등록이 끝난 상태에서:

```powershell
uv run --locked --extra ml --env-file .env python scripts/verify_stack.py
```

계정은 `DEMO_USERNAME`(기본 `demo`), 암호는 `DEMO_PASSWORD` 환경변수로 전달한다.
비밀번호를 명령행 인수·로그·결과 파일에 남기지 않는다. 두 번째 검증 계정이 있으면
`STACK_SECOND_USERNAME`, `STACK_SECOND_PASSWORD`를 환경에 넣어 소유권 검증도 수행한다.
두 번째 계정이 없으면 그 항목은 `not_run_no_second_account_credentials`로 명시한다.

Dispatcher 중단 후 outbox 복구 검사:

```powershell
uv run --locked --extra ml --env-file .env python scripts/verify_stack.py --recovery-dispatcher
```

이 옵션은 `option-risk-platform` Compose 프로젝트의 `dispatcher`만 중지한다.
중지 중 HTTP 202로 새 run을 생성하고, QUEUED 상태·빈 결과·null 합계가 유지되는지 확인한 뒤
`finally`에서 dispatcher를 재시작하고 정상 완료를 기다린다. DB·Redis·worker는 중지하지 않는다.

## 검사 범위

- Session 로그인/로그아웃, 로그인 CSRF, 인증된 쓰기 CSRF 및 익명 리소스 거부
- 금융 입력의 bool·잘못된 단위·부호·만기·불가능한 shock 거부
- 불변 입력 및 네 개 구성요소의 version ID/hash, 수정/삭제 API 거부
- HTTP 202·idempotency 동일 run 반환·다른 요청의 같은 key 충돌 409
- REFERENCE/COMPARE, quantity×multiplier, 완전한 포트폴리오 합계와 stress−base P&L
- Base reference 민감도의 유한성과 initial-volatility bump 단위
- 독립 수식에 의한 call-put parity와 ACT/365F·spot percent·rate bp·vol point 입력
- ML OOD를 이유와 함께 보존하고 reference를 유지하며 ML 합계/P&L을 null로 반환
- JSON/CSV export의 셀·provenance·완전성, 재실행의 원본 보존과 가격 재현
- 선택적 두 번째 계정의 타인 입력/run/export/retry 접근 거부
- 선택적 dispatcher 중단 후 durable outbox 재개

각 run은 기본 60초까지 기다린다. `--timeout`으로 조절할 수 있다.
기계 판독 결과는 Git에서 제외된 `work/stack-validation.json`에 기록된다.
HTTP POST 시간, 서버의 생성→완료 시간, polling을 포함한 wall time, worker 셀별 reference/ML
계산 시간을 구분한다. 작은 표본의 통합 검증이며 처리량 benchmark나 속도향상 주장이 아니다.

Worker 손실과 lease 복구는 별도 명령으로 검사한다. 이 명령은 worker를 강제 종료하므로
다른 계산이 없는 로컬 환경에서 실행한다.

```powershell
uv run --locked --extra ml --env-file .env python scripts/verify_worker_recovery.py --timeout 420
```

100 positions × 100 scenarios를 생성하고, read-only PostgreSQL 조회에서 RUNNING lease를
확인한 다음 이 프로젝트의 worker container에만 SIGKILL을 전송한다. `finally`에서 worker를
재시작한 뒤 기본 300초 lease의 실제 만료와 dispatcher 재전송을 기다린다. DB 시각이나 lease
만료값을 조작하지 않는다. 중단 직후 RUNNING인 chunk의 `attempts > 1` 및 `lease expired`
기록, 10,000개 고유 결과 셀, 100개 완전한 총계를 모두 만족해야 성공한다.
결과는 `work/worker-recovery.json`이며 소스 image ID와 run provenance도 포함한다.

## 실행 결과

2026-11-08 02:01 KST, `http://127.0.0.1:8000`의 Linux container 환경에서
두 사용자 계정과 `--recovery-dispatcher`를 포함한 **19개 검사·6개 실행이 통과**했다.
전체 실행시간은 20.24초였으며 종료 시 모든 서비스가 running 상태였다.

| Run | 셀 수 | POST 202 | 서버 생성→완료 | 제출→완료 polling wall |
| --- | ---: | ---: | ---: | ---: |
| REFERENCE | 4 | 52.45 ms | 0.333 s | 0.410 s |
| Worker 재시작 후 첫 COMPARE | 4 | 61.68 ms | 4.739 s | 4.859 s |
| REFERENCE 재실행 | 4 | 46.49 ms | 1.037 s | 1.227 s |
| Call-put parity·stress 단위 | 6 | 44.91 ms | 1.903 s | 2.083 s |
| ML 범위 밖·reference 유지 | 4 | 51.83 ms | 1.729 s | 2.033 s |
| Dispatcher 중단 후 복구 | 4 | 61.62 ms | 4.022 s | 4.199 s |

COMPARE의 ML 셀 계산 시간은 약 0.18~0.79ms였다.
Reference base 셀에는 bump/reprice 민감도 계산도 포함된다. Artifact 로딩·처음 라이브러리
import·dispatcher 주기·DB/queue 대기 비용 때문에 per-cell 계산 시간의 합은 end-to-end
시간과 같지 않다. 최초 요청과 이후 warm 요청을 같은 성능 수치로 비교하지 않는다.

Dispatcher 중단 중 새 run은 HTTP 202로 접수되어 DB의 QUEUED 상태로 유지됐다.
결과는 비어 있고 총계·P&L은 null이었다. 재시작 후 모든 필수 셀이 중복 없이 저장되고 합계가 완성됐다.

두 번째 사용자 세션의 타인 입력·run·export 조회 및 입력 실행·run 재시도는 모두 HTTP 404로 거부됐다.
로컬 자동 진입 모드에서도 명시적으로 로그인한 사용자의 세션과 소유권이 보존됐다.
실행 ID, 셀별 시간, provenance, 총계는 로컬 `work/stack-final-validation.json`에 기록했다.

### SIGKILL 및 lease 복구

2026-11-08 01:55:13 KST에 별도 `verify_worker_recovery.py` 실험에서 worker container를
SIGKILL로 종료하고 즉시 재시작했다. 이때 계산 중이던 scenario 6·7의 lease가 남아 있었다.
계산이 끝난 9,800개 셀은 유지됐고, 288.7초 관측까지 두 chunk의 attempts는 1이었다.

300초 lease가 자연 만료된 후 dispatcher가 작업을 다시 발행했다. 서버에서는 run 생성 후
**301.819708초**에 완료됐으며, 20초 polling의 다음 관측인 중단 후 309.1초에 완료를 확인했다.
클라이언트 전체 관측 시간은 310.12초였다. DB 시각·lease 값을 앞당기지 않았다.

| 항목 | 관측 결과 |
| --- | --- |
| 계산 규모 | 100 positions × 100 scenarios |
| 완료 결과 | 10,000개 고유 셀, 100개 완전한 scenario 총계/P&L |
| 중단된 chunk | scenario 6·7, 두 chunk 모두 attempts=2 |
| 복구 근거 | 두 chunk의 `last_error`에 `Previous worker lease expired` 보존 |
| 중복 셀 | 0 |
| 실패값을 대신한 0 | 없음; 구성한 양의 가격 입력의 모든 reference price > 0 |
| 최종 상태 | 모든 chunk와 run COMPLETED; worker를 포함한 모든 서비스 running |

Run ID는 `899acb1d-deca-4980-ba1b-945d41c6542f`이며, DB snapshot과 20초 간격의
진행 기록은 로컬 `work/worker-recovery.json`에 있다. API·worker·dispatcher는 같은 이미지를 사용했다.

- Image ID: `5df9ab195e43a8481c6e2c9e88d4a99c2bfedc9193eaa9da27e45d970018d3d0`
- Run source SHA-256: `e065bb6aab7f0d702580d4722b3e9d277bc3db0b61fa559e339fbc055aa8a7ed`

중복 메시지, 오래된 attempt token, 저장 이후 재호출, 최대 재시도 실패는 별도의 worker 회귀 테스트로 검사한다.

### API 주소 변경 후 nginx 자동 복구

2026-11-08 02:08 KST에 프로젝트 Docker network의 사용 중인 주소를 확인한 뒤 API 주소를
`172.18.0.6`에서 미사용 주소 `172.18.0.200`으로 바꿨다. `api` DNS alias를 유지했으며,
web container 재시작 없이 일시적인 연결 실패 후 **3.54초에** nginx 경유
`/api/session/`이 HTTP 200과 인증된 demo session을 반환했다.
`finally`에서 원래 주소로 복원했고 같은 endpoint가 **3.55초에** 다시 HTTP 200으로 회복됐다.

web·API container의 ID와 StartedAt은 시험 전후 동일했다. Docker DNS를 5초 주기로 갱신하는
nginx upstream이 주소 변경을 반영했으며 전환 중에는 일시적인 연결 실패가 있었다.
관측 기록은 로컬 `work/nginx-dns-validation.json`에 보존했다.
