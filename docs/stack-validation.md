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

## 실행 결과

실제 Docker API 기동 후 실행 결과를 이 절에 기록한다. 현재 스크립트의 static check만
통과했으며, 아래 네트워크·queue 검증은 실행 완료를 기다리는 상태다.
Worker 프로세스 중단/lease 만료 복구는 이 스크립트의 dispatcher 실험과 별도 검증이다.
