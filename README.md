# Option Risk Platform

옵션 포트폴리오의 가격·민감도·스트레스 손익을 계산하고, Heston 기준 엔진과 ML 가격을 비교하는 Django 기반 금융 분석 프로젝트입니다.

![포지션 입력 화면 — 실제 로컬 실행](docs/images/positions.png)

## 주요 기능

| 화면 | 할 수 있는 일 |
| --- | --- |
| 포지션 | 수동·CSV 입력, 롱/숏·수량·계약 승수 검증, 변경 불가능한 입력 버전 저장 |
| 시장·시나리오 | 평가일·현물·금리·초기 변동성 설정, 가격·변동성·금리 충격 구성 |
| 평가 결과·이력 | 포지션별 가격, 기본 민감도, 스트레스 P&L·히트맵, 재실행, CSV/JSON 다운로드 |
| ML 검증 | 지원 영역, 가격·P&L 오차, 실행 시간, 학습 모델·검증 보고서 확인 |

| 스트레스 결과·민감도 | ML 검증 |
| --- | --- |
| ![실제 평가 결과 화면](docs/images/results.png) | ![실제 ML 검증 화면](docs/images/ml-validation.png) |

합성 지수 하나와 USD, 무배당 유럽형 현금결제 콜/풋, ACT/365F를 지원합니다.
위험중립 모형 평가와 결정론적 스트레스 분석이며 VaR·ES나 확률 예측을 제공하지 않습니다.

## 계산과 복구

- **재현 가능한 실행** — 입력·모델·코드·수치 설정을 버전과 해시로 고정합니다.
- **완전한 결과만 합산** — 실패한 가격은 이유와 함께 남기고, 모든 필수 셀이 성공해야 총액과 P&L을 제공합니다.
- **중단 후 복구** — 실행과 outbox를 함께 저장하고, 중복 메시지·작업자 유실·늦게 도착한 결과를 처리합니다.
- **기준 엔진 유지** — 가격과 기본 민감도는 QuantLib `AnalyticHestonEngine`을 사용하며 ML은 비교용으로 실행합니다.

Black–Scholes 직접 구현과 독립 가격·parity·경계 검증은 [수치 검증](docs/numerical-validation.md)에,
세션·CSRF·소유권·불변 데이터·작업 복구 설계는 [백엔드 설계](docs/backend-design.md)에 정리했습니다.

## ML 실측

Heston teacher로 학습한 작은 MLP가 정규화 콜 가격 `C/K`를 예측하고, 풋은 put-call parity로 구합니다.
모델 사양이 다르거나 지원 영역을 벗어나면 ML 결과를 만들지 않고 기준 엔진의 결과를 보존합니다.

| 로컬 CPU 검증 | 결과 |
| --- | ---: |
| 독립 검증 유효 표본 | 4,770건 |
| 정규화 가격 MAE | 0.00052578 |
| 정규화 가격 최대 절대오차 | 0.00751943 |

오차는 `|ML − reference| / K`이며 옵션 가격 대비 상대오차가 아닙니다.
동일 512건의 warm CPU 측정에서 배치 추론은 빨랐지만 **개별 호출은 기준 엔진보다 느렸습니다**.
표본별 오차, 짧은 만기·지원 경계의 한계, P&L 오차와 측정 조건은 [ML 검증 보고서](docs/ml-validation.md)를 참고하세요.

## 로컬 실행

Docker Desktop의 **Linux 엔진**, Python, **uv 0.13.7**이 필요합니다.
애플리케이션용 Python 3.12와 의존성은 uv가 준비합니다.

```powershell
# Windows에서 uv가 없을 때만 실행
python -m venv work/bootstrap
.\work\bootstrap\Scripts\python.exe -m pip install uv==0.13.7

# 저장소 루트에서 실행
python scripts/bootstrap_demo.py
```

uv가 이미 설치되어 있다면 마지막 명령만 실행하면 됩니다.
초기 설정은 비밀키 생성, DB 준비, ML 학습·검증, 이미지 빌드와 서비스 시작을 포함합니다.

**[http://127.0.0.1:5173](http://127.0.0.1:5173)**에서 계정 생성·비밀번호 입력 없이 작업공간을 엽니다.
포지션 입력 → 시장·시나리오 설정 → 입력 버전 저장 → 평가 실행 순서로 사용할 수 있습니다.
데이터와 실행 이력은 로컬에 보존됩니다. 외부 서버 배포와 인터넷 공개는 하지 않습니다.

```powershell
docker compose stop                                   # 데이터 유지, 서비스 중지
docker compose up -d db redis api worker dispatcher web # 다시 시작
```

## 검증

[GitHub Actions 전체 검증](https://github.com/limbj/option-risk-platform/actions/runs/42394826035)이 통과했습니다.

| 검사 | 확인 결과 |
| --- | --- |
| Python 전체 테스트 · host / Linux | 각각 443 통과, PostgreSQL 전용 4개는 별도 검사 |
| PostgreSQL · host / Linux | 각각 66 통과 — 불변성·동시성·복구 포함 |
| 프런트엔드 · 브라우저 | 단위 테스트 7개, Playwright 전체 흐름 통과 |
| 실제 HTTP·큐·작업자 | 19개 검사·6개 실행 통과 |
| 작업자 강제 종료 후 복구 | 10,000개 결과·100개 총계 복구, 중복 0건 |

```powershell
uv run --locked --extra ml pytest
```

개발 환경·PostgreSQL·브라우저 검사 명령은 [개발 가이드](docs/development.md)에 있습니다.
[CI 검증](docs/ci-validation.md)과 [실제 실행·복구 기록](docs/stack-validation.md)에서 상세 증거를 확인할 수 있습니다.

## 기술 구성

| 영역 | 구성 |
| --- | --- |
| 웹 | React · TypeScript · Vite · TanStack Query · Plotly |
| API·데이터 | Django 5.2 LTS · DRF · PostgreSQL |
| 계산·작업 | NumPy · SciPy · QuantLib · Celery · Redis |
| ML·실행 환경 | PyTorch CPU · Docker Compose · Gunicorn · Nginx |

`src/quant`와 `src/ml`은 Django·DB에서 독립적으로 사용할 수 있습니다.
금융 입력 단위는 [금융 계약](docs/financial-contracts.md), 서비스 운영은 [로컬 운영 가이드](docs/deployment.md)를 참고하세요.
