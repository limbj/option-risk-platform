# Heston 가격 근사 모델 검증

CPU에서 생성·학습·평가한 `artifacts/demo`의 검증 결과다.
이 모델은 **COMPARE 전용**이며 가격·민감도·stress P&L의 기준은 QuantLib reference다.

## 구현과 재현

`ml` 패키지 자체를 import할 때 Django·DB·PyTorch·가중치를 초기화하지 않는다.
`ml.dataset`, `ml.train`, `ml.inference`, `ml.validation`은 Django에 의존하지 않는다.

```powershell
uv sync --locked --extra ml
uv run --locked --extra ml python -m ml.train --output artifacts/baseline-new --dataset data/baseline-new.npz --samples 16000 --epochs 350
uv run --locked --extra ml python -m ml.evaluate --artifact artifacts/baseline-new --dataset data/baseline-new.npz --gates docs/ml-demo-gates.json --output artifacts/demo-new
uv run --locked --extra ml pytest tests/ml
```

기존 dataset/artifact 경로를 덮어쓰지 않는다. `data/`, `artifacts/`는 Git에서 제외한다.
Gate 실패 시 train/evaluate CLI는 실패 report와 manifest를 보존하고 종료코드 2를 반환하므로,
해당 학습·평가를 호출한 bootstrap과 CI는 등록 전에 중단된다.
`load_artifact(directory)`는 manifest와 validation report를 읽고 SHA-256을 확인한 뒤
`torch.load(..., weights_only=True, map_location="cpu")`로 가중치를 읽는다.
`Surrogate.price(contract, market, spec)` 및 `price_many(cases, spec)`가 가격을 반환한다.
지원 범위·모델 불일치·가격 경계 위반은 `UnsupportedInput`과 이유를 반환한다.
상위 계산기는 해당 ML 셀을 미완료로 두고 reference 결과를 보존한다.

## 모델·데이터 계약

| 항목 | 값 |
| --- | --- |
| Features, 고정 순서 | `log(S/K)`, ACT/365F 잔존만기 `T`, 연속복리 연율 `r`, 연율 변동성 `sigma0` |
| 지원 범위 | log(S/K): −0.4~0.4; T: 14/365~2년; r: −0.03~0.10; sigma0: 0.05~0.70 |
| 출력 | 정규화 call 가격 `C/K`; put은 동일 가정의 put-call parity로 계산 |
| 고정 Heston | kappa=2, theta=0.04, xi=0.3, rho=−0.7, q=0 |
| Teacher | QuantLib 1.44 `AnalyticHestonEngine`, Gauss-Laguerre integration order=144 |
| Network | 4→96→96→64→1, SiLU; normalized call의 lower/upper bound를 출력 구조에 포함 |
| 전처리 | 학습 표본의 feature mean/std; manifest와 가중치 buffer 일치 여부 검사 |
| 학습 | AdamW, 초기 lr=0.002, cosine schedule, batch 512, 350 epochs |
| 실행 | Python 3.12.16, NumPy 2.5.4, PyTorch 2.15.0+cpu, Windows 11, float32, CPU 1 thread |
| Seed | 1729; deterministic algorithms; best epoch=348, 독립 tuning split의 MSE로 선택 |

Teacher label은 float64이다. residual maturity는 실제 날짜로 환산하여 생성하므로
feature의 `T`와 QuantLib의 날짜 기반 `T`가 일치한다.
출력 bound 구조는 학습 모델의 일부이며, 추론 실패 값을 0으로 바꾸거나 사후 clamp하지 않는다.

학습에서 다음 연속 영역 전체를 제외하고 독립적으로 평가했다:
`log(S/K) ∈ [0.12, 0.22]`, `T ∈ [0.5, 1.0]`, `sigma0 ∈ [0.22, 0.38]`.
`r`는 지원 범위 전체에서 생성했다. Random·heldout·edge split은 checkpoint 선택에 사용하지 않았다.

유효 표본은 train 15,977, tune 1,599, random 1,593, heldout 1,600, edge 1,577개다.
요청한 전체 22,400건 중 54건(train 23, tune 1, random 7, heldout 0, edge 23)은
reference 가격이 엄격한 유효성 검사에 실패했다. 실패한 입력 feature와 원인을
`manifest.teacher_failures` 및 report에 보존했으며, label을 0으로 만들지 않았다.
**아래 정확도는 reference가 성공한 표본에 대한 수치이며 실패한 영역을 보장하지 않는다.**

## 독립 검증 결과

오차는 `|ML − reference|/K`이며 옵션 가격 대비 상대오차가 아니다.
아주 작은 OTM 가격에서 상대오차는 클 수 있다.

| 검증 집합 | 유효 개수 | 평균 | p95 | p99 | 최대 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Random | 1,593 | 0.00046088 | 0.00143806 | 0.00258371 | 0.00373852 |
| Heldout parameter region | 1,600 | 0.00038016 | 0.00068441 | 0.00081464 | 0.00153840 |
| Domain boundary | 1,577 | 0.00073909 | 0.00290562 | 0.00482802 | 0.00751943 |
| 전체 | 4,770 | 0.00052578 | 0.00160789 | 0.00373638 | 0.00751943 |

K=$100일 때 전체 평균 절대오차는 $0.05258, 최대는 $0.75194다.
경계 표본 중 30일 이하 211건은 평균 0.00184626, 최대 0.00751943로,
짧은 만기에서 오차가 더 컸다. ITM/OTM과 짧은 만기별 상세 집계는 JSON report에 있다.
정규화 허용오차 1e−7 기준 가격 bound 위반 0건, put-call parity 잔차 최대 0이었다.
범위 밖 moneyness·만기·금리·변동성 및 다른 model spec의 5건은 모두 이유와 함께 거부됐다.

40개 포트폴리오에 각각 call/put 4개, signed quantity `[2, −1, 3, −2]`, multiplier=100을
사용했다. 동일 평가일에서 spot +5%, initial-vol +5 percentage points, rate +100bp를
적용하고 reference와 ML 각각의 base/stress 가격으로 P&L을 구했다.
미완료 포트폴리오는 0개, P&L 절대오차 평균 $28.49, p95 $71.51, 최대 $72.89였다.
각 gross notional $80,000 대비 최대오차는 0.00091114(0.091114%)다.

## Baseline 관측 후 설정한 비교용 gate

위 baseline을 관측한 후 `ml-demo-gates.json`에 다음 허용치를 기록하고,
가중치를 바꾸지 않은 새 `artifacts/demo`에서 재검증했다. 모든 gate가 통과했다.
이 gate는 동일 시험 집합에 맞춘 첫 demo 수용 기준이며, 새로운 독립 dataset에서의
검증이나 실제 거래·위험관리 적합성을 대신하지 않는다.

| Gate | 허용치 |
| --- | ---: |
| 정규화 평균오차 | ≤ 0.001 |
| 정규화 p99 오차 | ≤ 0.005 |
| 정규화 최대오차 | ≤ 0.01 |
| P&L 최대오차 / gross notional | ≤ 0.0015 |
| 가격 bound 위반, 미완료 포트폴리오 | 0 |
| OOD/model mismatch 거부 | 5/5 |
| 정규화 parity residual | < 1e−12 |

성능은 보고 항목이며 최소 속도향상은 gate에 포함하지 않는다.

## 동등 workload 벤치마크

동일 512개 call 입력, CPU 1 thread, 양쪽 warm-up 후 5회 중앙값이다.
QuantLib은 같은 모델/엔진 객체를 재사용하며, ML에서도 입력 검증을 포함한 경로와
사전 생성 tensor만 계산하는 경로를 구분했다.

| 경로 | 512건 시간 |
| --- | ---: |
| Reused QuantLib reference | 45.276 ms |
| ML batch + 입력/결과 검증 | 1.717 ms |
| ML 개별 호출 + 입력/결과 검증 | 64.144 ms |
| ML tensor 계산만 | 0.373 ms |

Batch는 이 workload에서 약 26.37배 빠르지만 **개별 호출은 reference보다 느렸다**.
현재 worker의 개별 셀 경로에 batch 수치를 적용할 수 없다. 서로 다른 정확도의 모델이며,
네트워크·API·DB·queue·artifact 최초 로딩 시간도 이 표에 포함하지 않았다.
API 응답 및 worker 셀별 timing은 실행 report에서 따로 확인한다.

## 추적 정보

Manifest는 feature 순서/전처리/지원 영역/고정 모델/teacher 수치 설정/seed/software versions/
dtype/device/source hashes/dataset hash/weights hash/validation report hash를 기록한다.
추론시 manifest 사본을 변경해도 로드된 모델의 지원 범위를 변경할 수 없다.

- Dataset 내용 SHA-256: `64cfcc4130ab8d5bfd59e4feac4656bb4b51e28e4352175e64ad96d1a44cc01b`
- 가중치 SHA-256: `c6e617ba3c7fa0877b24be01dc9580dfab5ac0754ee3bd8abc5986cc8b52e903`
- 첫 생성 3.45초, 학습 22.10초; 이후 환경 부하에 따라 달라질 수 있다.

환경·PyTorch 버전·플랫폼이 바뀐 실행의 bitwise 일치는 보장하지 않는다.
공식 근거: [PyTorch reproducibility](https://docs.pytorch.org/docs/stable/notes/randomness.html),
[restricted torch.load](https://docs.pytorch.org/docs/stable/generated/torch.load.html).
