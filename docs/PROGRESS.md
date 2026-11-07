# MVP 진행 기록

기준 날짜: 2026-11-08 (Asia/Seoul). 사용자 지시에 따라 1~7단계를 계속 진행한다.
추가 사용자 지시로 검증된 중간 단계의 커밋·push를 허용받았다. 외부 배포는 별도 지시 전 실행하지 않는다.

## 확인된 완료

- **1단계**: Python 3.12.16, uv 0.13.7, Django 5.2.19, DRF 3.18.3.
  Django 5개 앱·PostgreSQL 설정·세션/CSRF·health, 독립 quant/ml, 불변 입력 계약,
  strict JSON parser와 샘플, 잠금 파일·Compose·CI 구성.
- **검증**: Windows 267 passed (3.10s), Linux Docker 267 passed (2.08s).
  Ruff lint/format 통과. Django system check 0 issues; migrations drift 없음.
  금융 규칙 255개, Django/패키지 경계 12개. Linux 엔진 기동 및 이미지 빌드 확인.

## 진행 중

- 2~3단계: Black–Scholes, stress, complete-only 집계, Heston 기준 가격·민감도.
- 4단계: 불변 ORM 버전, 사용자 소유권 API, durable outbox와 idempotent worker/recovery.
- 5단계: React/Vite 사용자 화면과 입력·결과 흐름.
- 6단계: Heston teacher 데이터·MLP·독립 검증·manifest·COMPARE 연결.

## 중간 검증 체크포인트

- **2~3단계 완료**: 금융 테스트 355개. BS 독립 가격·QL 대조, Heston 분산 극한·144/192점 수렴,
  평가일 격리, Delta/Gamma/초기변동성 민감도와 완결성 집계 검증.
- **4단계 완료**: 실제 PostgreSQL 테스트 51개 통과. 소유권/CSRF/동시 요청/lease fencing/
  재발행/실패 복구/DB trigger/terminal sealing 동시성/모델 보관·보고서 hash 검증.
- **6단계 오프라인 완료**: train 15,977 유효 표본, 독립 검증 4,770 표본,
  normalized 가격 MAE 0.0005258 / max 0.007519. 비교용 gate 통과. ML 테스트 25개.
- **전체 호스트 검사**: 428 passed, PG전용 4개 skipped (PG 별도 검사에서는 통과).
  Ruff·migration drift 검사 통과. 프론트 TypeScript/build·CSV 테스트 7개 통과, npm audit 0건.
- **남은 통합 검증**: Linux 서비스 전체 API/queue/worker, dispatcher 중단복구, Playwright,
  최신 소스 컨테이너 전체 검사와 원격 CI. 웹 포트는 Windows 8080 바인딩 실패에 따라 5173으로 선택했다.

## 다음 검증

각 컴포넌트 테스트 후 PostgreSQL/Redis/Linux worker 통합, 실제 학습 산출물 검증,
브라우저 E2E, 복구 시나리오, 배포용 로컬 Compose 데모를 확인한다.
현재 2~7단계는 완료로 표시하지 않는다. 가격 실패와 불완전 합계는 0으로 대체하지 않는다.
