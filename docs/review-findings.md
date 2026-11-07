# Stage 4 독립 백엔드 검토

검토일: 2026-11-08. 대상은 소유권/세션 인증, 입력 버전, 실행 provenance,
outbox, lease·attempt fencing, 결과 불변성, 불완전 합계와 P&L이다.
검토 에이전트는 회귀 테스트를 작성하고 구현 담당자가 애플리케이션 코드를 수정했다.

## 발견 및 수정

| 발견 | 영향 | 반영된 수정 |
| --- | --- | --- |
| 워커가 코드 hash만 확인하고 pinned software versions를 대조하지 않음 | 다른 QuantLib 등으로 계산하고 원래 실행 환경 라벨을 보고할 수 있음 | 계산 전 실제 라이브러리 버전과 run의 버전을 비교하고 불일치 셀은 명시적 실패 처리 |
| 개별 snapshot hash만 확인하며 run에 고정된 hash/ID/scenario/base index와 재대조하지 않음 | 초기 삽입·복구에서 잘못 연결된 provenance가 정상 가격과 함께 보고될 수 있음 | `verify_run_inputs`에서 소유자, 입력 및 구성 hash/ID, valuation date, 실행 시나리오, base index, artifact pin 대조 |
| 불변성 guard가 결과 UPDATE/DELETE만 차단함 | 완료 결과에 새 행 추가, 다른 run의 chunk 연결, 범위 밖 position/scenario 추가 가능 | ORM 생성 검증 및 PostgreSQL INSERT trigger 추가. 상태·부모·인덱스 검증, run→chunk 순서 잠금으로 완료 처리와 직렬화 |

기본 입력 API나 정상 worker 경로에서 즉시 외부 사용자가 임의 INSERT를 수행할 수
있다는 의미는 아니다. 입력/결과를 복구하거나 ORM·SQL로 다루는 경로까지 포함한
불변성 경계를 강화했다. PostgreSQL을 영속성 검증의 기준으로 삼는다.

## 회귀 테스트

`tests/django/test_review_regressions.py`에 13개 검증 사례를 추가했다.

- QuantLib 버전 불일치 시 기준 가격을 생성하지 않고 실패 기록
- run의 입력 hash, 구성 hash, 버전 ID, 시나리오, base index 불일치 거부
- 완료 결과·chunk에 추가 행 생성 거부, 다른 run의 chunk를 사용한 결과 거부
- PostgreSQL raw SQL을 통한 완료 결과 추가 거부
- PostgreSQL에서 완료 처리가 보유한 run 잠금과 결과 INSERT 경합 재현
- 아직 재회수하지 않았어도 만료된 attempt token으로 finalize 불가
- outbox lease를 새 dispatcher가 소유하면 이전 dispatcher의 ACK 기록 불가

SQLite 독립 회귀: **11 passed, 2 PostgreSQL 전용 skipped**.
Ruff 검사 및 포맷 검사: 통과.
PostgreSQL 전체 `tests/django`: **47 passed, 0 skipped, 0 warnings** (20.36초).
구현 담당자가 별도 PostgreSQL 테스트 데이터베이스에서 실행했으며,
독립 회귀 13개와 실제 INSERT/완료 상태 경합 테스트가 모두 포함되어 통과했다.

## 확인한 기존 동작

소유자가 다른 입력·실행·재시도·export는 404로 제한되고, 세션 로그인과 인증 후
변경 요청은 CSRF 검증을 거친다. run 및 outbox는 같은 transaction에서 생성된다.
중복 요청은 소유자별 idempotency key로 합쳐지고, 다른 요청을 같은 key로 보내면
충돌한다. 워커는 lease와 attempt token을 확인하며 계산 중 transaction을 유지하지
않는다. outbox publish ACK 유실은 중복 발행을 허용하고, 결과 고유성 및 fencing으로
중복 저장을 방지한다. 발행 후 큐에서 소실된 작업도 recovery가 다시 발행한다.

실패한 기준 가격은 `None`으로 남고, 기준 또는 스트레스 시나리오에 필수 셀이
누락되면 해당 합계/P&L도 `None`이다. ML 실패는 이유를 남기고 기준 결과를 보존한다.
비교 P&L은 기준 엔진끼리, 동일 artifact의 ML 결과끼리 계산하며 상호 대체하지 않는다.

SQLite의 빠른 검증은 PostgreSQL row lock 및 raw SQL 불변성 검증을 대체하지 않는다.
