# 실제 Docker stack 검증

`scripts/verify_stack.py`는 Django 테스트 클라이언트를 사용하지 않고 실제 HTTP endpoint를
호출한다. PostgreSQL에 저장된 입력·run, durable outbox, Redis, Celery worker와 ML artifact를
거친 결과를 확인한다. Python 표준 라이브러리만 사용한다.

## 실행

API·worker·dispatcher가 기동되어 있고 migration·demo 계정·ML artifact 등록이 끝난 상태에서:

```powershell
uv run --locked --extra ml --env-file .env python scripts/verify_stack.py
```

계정은 `DEMO_USERNAME`(기본 `demo`), 암호는 `DEMO_PASSWORD` 환경변수로 전달한다.
비밀번호를 명령행 인수·로그·결과 파일에 남기지 않는다. 두 번째 검증 계정이 있으면
`STACK_SECOND_USERNAME`, `STACK_SECOND_PASSWORD`를 환경에 넣어 소유권 검증도 수행한다.
두 번째 계정이 없으면 그 항목은 `not_run_no_second_account_credentials`로 명시한다.

프로젝트 dispatcher를 잠시 멈추는 실제 outbox 복구 검증은 명시적으로 실행한다:

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
- 선택적 실제 dispatcher 중단 후 durable outbox 재개

각 run은 기본 60초까지 기다린다. `--timeout`으로 조절할 수 있다.
기계 판독 결과는 Git에서 제외된 `work/stack-validation.json`에 기록된다.
HTTP POST 시간, 서버의 생성→완료 시간, polling을 포함한 wall time, worker 셀별 reference/ML
계산 시간을 구분한다. 작은 표본의 통합 검증이며 처리량 benchmark나 속도향상 주장이 아니다.

실제 worker 손실/lease 복구를 별도로 검증하는 명령은 다음과 같다. 이 명령은 로컬 검증용이며,
다른 사용자가 계산 중인 stack에서는 실행하지 않는다.

```powershell
uv run --locked --extra ml --env-file .env python scripts/verify_worker_recovery.py --timeout 420
```

100 positions × 100 scenarios를 생성하고, read-only PostgreSQL 조회에서 RUNNING lease를
확인한 다음 이 프로젝트의 worker container에만 SIGKILL을 전송한다. `finally`에서 worker를
재시작한 뒤 기본 300초 lease의 실제 만료와 dispatcher 재전송을 기다린다. DB 시각이나 lease
만료값을 조작하지 않는다. 처음 RUNNING이었던 chunk의 `attempts > 1` 및 `lease expired`
기록, 10,000개 고유 결과 셀, 100개 완전한 총계를 모두 만족해야 성공한다.
결과는 `work/worker-recovery.json`이며 소스 image ID와 run provenance도 포함한다.

## 실행 결과

2026-11-08 01:45 KST, `http://127.0.0.1:8000`의 실제 Linux container stack에서
`--recovery-dispatcher`를 포함하여 실행했다. **18개 검사·6개 run이 모두 통과**했고,
전체 실행시간은 25.09초였다. API·PostgreSQL·Redis·prefork Celery worker·dispatcher가
실제로 동작했으며, 마지막에 모든 서비스가 running임을 확인했다.

| Run | 셀 수 | POST 202 | 서버 생성→완료 | 제출→완료 polling wall |
| --- | ---: | ---: | ---: | ---: |
| REFERENCE | 4 | 83.69 ms | 2.534 s | 2.728 s |
| 최초 COMPARE | 4 | 49.49 ms | 5.749 s | 6.049 s |
| REFERENCE 재실행 | 4 | 49.36 ms | 1.334 s | 1.486 s |
| Call-put parity·stress 단위 | 6 | 52.53 ms | 1.972 s | 2.302 s |
| ML 범위 밖·reference 유지 | 4 | 67.57 ms | 1.679 s | 1.792 s |
| Dispatcher 중단 후 복구 | 4 | 59.42 ms | 4.608 s | 4.875 s |

첫 COMPARE의 첫 ML 셀은 약 27.4~27.9ms였고 이후 warm ML 셀은 약 0.13~0.32ms였다.
Reference base 셀에는 bump/reprice 민감도 계산도 포함된다. Artifact 로딩·처음 라이브러리
import·dispatcher 주기·DB/queue 대기 비용 때문에 per-cell 계산 시간의 합은 end-to-end
시간과 같지 않다. 위 최초 요청과 이후 warm 요청을 같은 성능 수치로 비교하지 않는다.

Dispatcher 중단 중 새 run의 202 접수·DB 보존·QUEUED·빈 결과·null 총계/P&L을 확인했다.
재시작 이후 모든 required cell이 정확히 한 번씩 보고되고 합계가 완성됐다.
이는 실제 durable outbox 재개 검증이다. Worker 프로세스 중단/lease 만료 복구는
이 dispatcher 실험과 별도의 시험이며 이 스크립트에서는 실행하지 않았다.

두 번째 계정의 credential을 이 실행에 제공하지 않아 cross-owner HTTP 검증은
`not_run_no_second_account_credentials`로 명시했다. 별도의 Django ownership 회귀 테스트와
구분하며, 실제 두 계정 네트워크 시험을 수행한 것으로 주장하지 않는다.
상세 ID·각 셀 timing·pinned provenance·총계는 `work/stack-validation.json`에 남아 있다.
