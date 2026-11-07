# 금융 계산 검증 — Stage 2 / Stage 3

검증일: 2026-11-08. Python 3.12.16, QuantLib 1.44, float64.
`uv.lock`으로 실행 환경을 고정한다. 이 문서는 계산 검증을 다루며 API,
데이터베이스, 워커 복구, ML 근사 품질 검증과 구분한다.

## 구현과 단위

- `quant.pricing.black_scholes`: 유럽형 현금결제 콜/풋의 직접 구현.
  비배당 지수 하나, USD, 연속복리 단일 금리, ACT/365F를 사용한다.
- `quant.heston.HestonPricer`: QuantLib `AnalyticHestonEngine`, Gatheral 형식,
  Gauss-Laguerre 적분 144점. 수렴 비교에는 192점을 사용한다. 모델의
  `kappa/theta/xi/rho`는 고정하며 시장 입력은 `spot/rate/sigma0`이다.
- `quant.stress.apply_stress`: spot `-10`은 상대 -10%, sigma0 `+5`는
  절대 +0.05, rate `+100`은 +0.01. 날짜와 잔존 만기는 유지한다.
  Heston의 새 초기분산은 `(sigma0 + delta_sigma0)²`다.
- `quant.risk.sensitivities`: 기준 엔진을 중심차분으로 재평가한다.
  기본 spot bump는 `spot * 1e-4`, sigma0 bump는 `1e-4`다. 반환되는
  Delta/Gamma는 단위 옵션의 spot 1단위/제곱단위당 미분이며,
  `initial_volatility_sensitivity`는 sigma0 **1.0당** 가격 미분이다.
  1 volatility percentage point 표시값은 이 값에 **0.01**을 곱한다.
  실제 절대 bump 두 개를 결과에 저장한다. 중앙차분의 양쪽 입력이
  양수가 아니거나 부동소수점으로 표현할 수 없으면 명시적으로 실패한다.
- 포지션 가치는 `signed quantity * multiplier * per-unit price`다.
  `aggregate_portfolio`는 모든 필수 포지션이 성공한 경우만 합계를 낸다.
  실패/누락 시 `total=None`이고 원인을 보존한다. `stress_pnl`도 양쪽
  합계가 완전하고 포지션 집합 및 모델/엔진/버전 라벨이 같아야 계산한다.

## 검증 결과와 허용오차

`uv run --locked pytest tests/quant -q`: **355 passed**.
`ruff check`, `ruff format --check`: 통과.

| 검증 | 조건 / 기준 | 절대 허용오차 |
| --- | --- | --- |
| BS 독립 기준값 | S=K=100, T=1, r=.05, sigma=.20, q=0; call=10.450583572185565, put=5.573526022256971 | 1e-12 |
| BS 별도 엔진 교차검증 | QuantLib AnalyticEuropeanEngine; 콜/풋, 음의 금리, 1일~2년, 변동성 .1~.8 | 1e-11 |
| BS parity / bounds | S=50/100/150, 1/30/365/730일, r=-.05/0/.08 | 1e-11 |
| Heston 일정분산 극한 | xi=1e-4, rho=0, theta=v0; 6개 콜/풋·spot 조합을 BS와 비교 | 2e-7 |
| Heston 결정적 평균회귀 분산 극한 | xi=1e-4, rho=0; 적분분산의 닫힌식을 BS에 대입 | 2e-7 |
| Heston parity / bounds | 음의 금리, ATM 1일, 30일, 1~2년 | 1e-10 |
| Heston 적분 수렴 | 동일 입력의 144점 대 192점 | 2e-8 |
| BS 감응도 | 해석적 Delta/Gamma/vol 미분 | 1e-8 / 1e-8 / 1e-5 |
| Heston bump 수렴 | 기본 bump와 두 배 bump의 Delta/Gamma/initial-vol 미분 | 1e-7 / 1e-8 / 2e-6 |

추가 테스트는 long/short 부호, 음의 금리 스트레스, 초기변동성의 절대 변화,
무효 shock 거부, 누락·실패 합계, source 불일치, overflow, 날짜 범위,
성공/실패 시 QuantLib 설정 복원, 공유 adapter 동시호출 시 날짜 격리를 확인한다.

재현용 Heston 기준 입력: valuation date=2027-01-01, expiry=2028-01-01,
S=K=100, r=.05, sigma0=.20, kappa=2, theta=.04, xi=.3, rho=-.7.

| 측정 항목 | 관측값 |
| --- | --- |
| Heston call, 144점 | 10.39421856515017 |
| Heston call, 192점 | 10.394218565150176 |
| Delta | 0.6918672047088847 |
| Gamma | 0.017409180017580184 |
| Initial-volatility sensitivity, sigma0 1.0당 | 15.685218881165142 |
| Initial-volatility sensitivity, 1pp당 | 0.15685218881165142 |
| 일정분산 극한 6개 최대 가격 오차 | 6.245874928367812e-9 |
| 결정적 평균회귀 분산 극한 가격 오차 | 1.5096974337325264e-8 |
| bump 절반 축소 시 Delta / Gamma / vol 미분 차이 | 4.39e-8 / 6.84e-10 / 1.45e-6 |

## 계산 실패와 운영 경계

가격은 비유한값이나 음수이면 `PricingError`로 실패한다. 기타 가격 경계
오차는 `1e-10 * max(1, spot, upper_bound)`까지만 허용하며 원값을 유지한다.
가격이나 shock을 0 또는 경계값으로 치환하지 않는다. 극단 OTM/단기 등에서
수치 적분이 작은 음수를 돌려주더라도 실패 이유를 보존한다. 위 테스트 통과가
모든 입력에서 144점의 정확도를 보증하지는 않는다.

동일 valuation date에서는 spot/rate quote와 v0를 갱신하고 모델·엔진을 재사용한다.
날짜가 바뀌면 곡선을 다시 생성한다. 모듈의 공유 lock과 `SavedSettings`가
설정 변경·평가·복원을 보호한다. 이 lock을 사용하지 않는 외부 QuantLib 코드까지
격리하는 것은 아니므로 워커는 합의대로 **별도 Linux 프로세스**를 사용한다.
QuantLib 날짜 범위(1901~2199) 밖 입력도 명시적 계산 실패다.

Feller 조건은 금융 계약의 필수 제약으로 강제하지 않는다. 위험 감응도는 기준
엔진에서만 계산하며, ML 미분이나 성능 개선은 이 문서의 검증 대상이 아니다.

## 근거

적분 설정과 수치 극한 검증 방법은 QuantLib의 공식
[AnalyticHestonEngine 선언](https://github.com/lballabio/QuantLib/blob/master/ql/pricingengines/vanilla/analytichestonengine.hpp)
및 [Heston 테스트](https://github.com/lballabio/QuantLib/blob/master/test-suite/hestonmodel.cpp)의
`testAnalyticVsBlack`를 확인했다. 재사용 시 파라미터 순서
`theta, kappa, xi, rho, v0`는 공식
[HestonModel 구현](https://github.com/lballabio/QuantLib/blob/master/ql/models/equity/hestonmodel.cpp)을
확인했다. 본 프로젝트의 비배당·ACT/365F 입력으로 별도 검증한다.
