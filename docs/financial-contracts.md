# 금융 계약과 입력 규칙

현재 지원 범위는 배당 없는 합성 지수 `SYNTH_INDEX`, 통화 `USD`, 유럽형 현금결제
콜/풋이다. q = 0은 고정 가정이므로 입력에서 배당·행사 방식·다른 통화를 받지 않는다.
외부 JSON 스키마는 `examples/stage1_inputs.json`으로 확인할 수 있다.

## 계약과 포지션

`OptionContract`는 `option_type`(call/put), `strike`, `expiry`, `underlying`, `currency`다.
파서는 문자열을 enum/date로 변환하고, Python 값 객체 생성은 해당 enum/date 타입을 요구한다.

`Position`은 계약, `side`(long/short), 부호 있는 `quantity`, 양수 `multiplier`다.
long은 quantity > 0, short는 quantity < 0이다. `True`, 소수 계약 수, 0은 거부한다.
가치 계산은 이후 **quantity × multiplier × 옵션 단위 가격**으로 구현한다.

날짜는 시간대 없는 ISO `YYYY-MM-DD`이며 datetime은 받지 않는다. 평가일 < 만기일이어야 한다.
ACT/365F의 T는 실제 경과일 / 365이다. 윤일을 실제 일수에 포함하되 분모는 항상 365다.

## 시장과 모델

| 필드 | 의미·단위 | 검증 |
|---|---|---|
| spot, strike | 지수 수준 | 양의 유한 실수 |
| rate | 연속복리 연율 소수 (0.03 = 3%) | 유한 실수, 음수 허용 |
| sigma0 | 연율 초기 변동성 소수 (0.2 = 20%) | 양수; v0 = sigma0²도 양의 유한 값 |
| kappa | 분산 평균회귀 속도, 1/년 | 양의 유한 실수 |
| theta | 장기 분산 수준 | 양의 유한 실수 |
| xi | Heston variance SDE의 vol-of-vol 계수 | 양의 유한 실수 |
| rho | 주가·분산 Brownian 상관계수 | 유한 실수, [-1, 1] |
| multiplier | 1계약당 가격 단위 승수 | 양의 유한 실수 |

Heston 프로파일은 별도 `HestonModelSpec` 값 객체로 고정한다. Feller 조건
2κθ ≥ ξ²는 경계 거동의 조건이며 입력의 필수 제약으로 강제하지 않는다. 실제 참조 엔진의
수치 지원 범위와 정확성은 3단계에서 검증한다. 현재 생성자가 모델 가격의 유효성을 보장하지는 않는다.

숫자 필드는 JSON number/Python int·float만 받는다. bool, 숫자 문자열, NaN, ±Infinity,
float 변환 오버플로를 거부한다. 이미 소수 단위로 전달한 rate/sigma0가 작성자의 의도와
일치하는지는 자동 추정하지 않는다. 임의의 상한이나 추측에 의한 단위 보정을 하지 않는다.

## 시나리오

| 입력 필드 | 예 | 정규화된 변화량 |
|---|---|---|
| spot_shock_pct | 10 | +0.10 상대 변화 |
| sigma0_shock_pp | 5 | +0.05 절대 변동성 변화 |
| rate_shock_bp | 100 | +0.01 절대 금리 변화 |

모든 스트레스는 순간 변화로 평가일·잔존만기·Heston 고정 파라미터를 유지한다.
volatility stress는 **v0_new = (sigma0 + sigma0_change)²**다.
`validate_for(market)`는 스트레스 후 spot/sigma0/v0가 양의 유한 값이고 rate가 유한 값인지
확인한다. 유효하지 않은 충격을 clamp하지 않는다. 시장 변환과 P&L 계산은 2단계 대상이다.

## 입력 묶음과 오류

`parse_inputs(payload)`는 `market`, `model`, `positions`, `scenarios`를 받아 변경 불가능한
`InputBundle`을 반환한다. 중첩 객체도 검증하며 정의되지 않은 키·누락된 필수 키·잘못된
타입을 거부한다. 포지션과 시나리오는 각각 1~100개이며 시나리오 이름은 중복할 수 없다.
포지션의 만기와 식별자, 모든 시나리오를 같은 시장 스냅샷에 대해 검증한다.

도메인 오류는 `ContractValidationError` (`ValueError` 하위 클래스)다. 파서는 가격,
변환된 시장, 0으로 치환된 결과를 생성하지 않는다. CSV/HTTP 어댑터는 후속 단계에서
동일한 검증 계약을 호출한다. 고정 입력과 모델의 영속 버전·해시·계산 출처는 4단계에서 연결한다.
