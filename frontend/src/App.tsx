import { lazy, Suspense, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setCsrf } from "./api";
import { downloadText, parsePositionsCSV } from "./csv";
import ModelSummary from "./ModelSummary";
import type {
  Artifact,
  Inputs,
  InputVersion,
  Position,
  Run,
  Scenario,
} from "./types";

const StressChart = lazy(() => import("./StressChart"));
const money = (value: number | null | undefined, decimals = 2) =>
  value == null
    ? "—"
    : value.toLocaleString("en-US", {
        maximumFractionDigits: decimals,
        minimumFractionDigits: decimals,
      });
const statusLabel: Record<string, string> = {
  QUEUED: "대기 중",
  RUNNING: "계산 중",
  COMPLETED: "완료",
  PARTIAL_ERROR: "부분 실패",
  FAILED: "실패",
};
const tabs = [
  "포지션",
  "시장 · 시나리오",
  "평가 · 실행 이력",
  "ML 검증",
] as const;
const pending = (run?: Run) =>
  !!run && ["QUEUED", "RUNNING"].includes(run.status);
type Session = {
  authenticated: boolean;
  user: { id: number; username: string } | null;
  csrfToken: string;
  localDemoMode?: boolean;
};

function BrandMark() {
  return (
    <svg
      className="brand-mark"
      width="30"
      height="30"
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M5 5v22h23"
        stroke="currentColor"
        strokeWidth="1.5"
        opacity="0.35"
      />
      <path
        d="M5 23h11L28 9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function NavigationIcon({ index }: { index: number }) {
  const paths = [
    "M4 4h16v16H4z M4 10h16 M10 4v16",
    "M4 18V6 M10 18V3 M16 18V9 M22 18V5 M2 21h22",
    "M3 18l5-5 4 2 8-10 M15 5h5v5",
    "M8 3h8l5 9-5 9H8l-5-9z M8 3l4 9 4-9 M3 12h18 M8 21l4-9 4 9",
  ];
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[index]} />
    </svg>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step = "any",
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  step?: string;
}) {
  return (
    <label>
      {label}
      <input
        className="numeric-input"
        type="number"
        required
        step={step}
        value={Number.isNaN(value) ? "" : value}
        onChange={(e) =>
          onChange(e.target.value === "" ? NaN : Number(e.target.value))
        }
      />
    </label>
  );
}

export default function App() {
  const client = useQueryClient();
  const [tab, setTab] = useState<(typeof tabs)[number]>("포지션");
  const [inputs, setInputs] = useState<Inputs>();
  const [name, setName] = useState("Synthetic index book");
  const [saved, setSaved] = useState<InputVersion>();
  const [selectedRun, setSelectedRun] = useState<string>();
  const [mode, setMode] = useState("REFERENCE");
  const [artifactId, setArtifactId] = useState("");
  const [selectedReportId, setSelectedReportId] = useState("");
  const [notice, setNotice] = useState("");
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => api<Session>("session/"),
    retry: false,
  });
  useEffect(() => {
    if (session.data) setCsrf(session.data.csrfToken);
  }, [session.data]);
  const loggedIn = !!session.data?.authenticated;
  const sample = useQuery({
    queryKey: ["sample"],
    queryFn: () => api<Inputs>("sample/"),
    enabled: loggedIn,
  });
  useEffect(() => {
    if (sample.data && !inputs) setInputs(structuredClone(sample.data));
  }, [sample.data, inputs]);
  const snapshots = useQuery({
    queryKey: ["inputs"],
    queryFn: () => api<{ items: InputVersion[] }>("inputs/"),
    enabled: loggedIn,
  });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<{ items: Run[] }>("runs/"),
    enabled: loggedIn,
    refetchInterval: (query) =>
      query.state.data?.items.some(pending) ? 2000 : false,
  });
  const run = useQuery({
    queryKey: ["run", selectedRun],
    queryFn: () => api<Run>(`runs/${selectedRun}/`),
    enabled: loggedIn && !!selectedRun,
    refetchInterval: (query) => (pending(query.state.data) ? 1000 : false),
  });
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [tab]);
  useEffect(() => {
    if (run.data && !pending(run.data)) {
      client.invalidateQueries({ queryKey: ["runs"] });
    }
  }, [run.data?.status, selectedRun, client]);
  const artifacts = useQuery({
    queryKey: ["models"],
    queryFn: () => api<{ items: Artifact[] }>("models/"),
    enabled: loggedIn,
  });
  const reportArtifact =
    artifacts.data?.items.find((item) => item.id === selectedReportId) ??
    artifacts.data?.items[0];
  const edit = (next: Inputs) => {
    setInputs(next);
    setSaved(undefined);
    setNotice("");
  };
  const login = useMutation({
    mutationFn: (data: { username: string; password: string }) =>
      api("login/", data),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["session"] });
    },
  });
  const save = useMutation({
    mutationFn: () => api<InputVersion>("inputs/", { name, inputs }),
    onSuccess: (data) => {
      setSaved(data);
      setNotice(
        "입력 버전을 저장했습니다. 이후 수정은 새 버전으로 저장됩니다.",
      );
      client.invalidateQueries({ queryKey: ["inputs"] });
    },
  });
  const launch = useMutation({
    mutationFn: () =>
      api<Run>("runs/", {
        input_id: saved!.id,
        mode,
        idempotency_key: crypto.randomUUID(),
        ...(mode === "COMPARE" ? { artifact_id: artifactId } : {}),
      }),
    onSuccess: (data) => {
      setSelectedRun(data.id);
      setNotice("");
      setTab("평가 · 실행 이력");
      client.invalidateQueries({ queryKey: ["runs"] });
    },
  });
  const retry = useMutation({
    mutationFn: () =>
      api<Run>(`runs/${selectedRun}/retry/`, {
        idempotency_key: crypto.randomUUID(),
      }),
    onSuccess: (data) => {
      setSelectedRun(data.id);
      client.invalidateQueries({ queryKey: ["runs"] });
    },
  });
  const error = [
    session.error,
    sample.error,
    snapshots.error,
    runs.error,
    run.error,
    artifacts.error,
    save.error,
    launch.error,
    retry.error,
  ].find(Boolean);

  if (session.isPending)
    return (
      <main className="empty">
        <h1>Option Risk</h1>
        <p>작업공간을 열고 있습니다.</p>
      </main>
    );

  if (!loggedIn)
    return (
      <main className="login-shell">
        <section className="login-story">
          <div className="brand">
            <BrandMark />
            <span>
              OPTION <b>RISK</b>
            </span>
          </div>
          <div>
            <h1>옵션 포트폴리오 평가</h1>
            <p>
              포지션과 시장 입력을 저장하고 가격·민감도·스트레스 손익을
              확인합니다.
            </p>
          </div>
          <span className="fine">유럽형 옵션 · USD · ACT/365F</span>
        </section>
        <section className="login-card">
          <h2>작업공간 로그인</h2>
          <p className="muted">사용자 이름과 비밀번호를 입력하세요.</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const form = new FormData(e.currentTarget);
              login.mutate({
                username: String(form.get("username")),
                password: String(form.get("password")),
              });
            }}
          >
            <label>
              사용자 이름
              <input
                name="username"
                autoComplete="username"
                required
                defaultValue="demo"
              />
            </label>
            <label>
              비밀번호
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </label>
            <button
              className="primary"
              disabled={!session.data || login.isPending}
            >
              로그인
            </button>
            {(login.error || session.error) && (
              <p role="alert" className="error">
                {(login.error || session.error)?.message}
              </p>
            )}
          </form>
          <p className="fine muted">
            합성 지수의 옵션을 고정된 Heston 모형으로 평가합니다.
          </p>
        </section>
      </main>
    );

  return (
    <div className="shell">
      <aside className="workspace-bar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setTab("포지션");
          }}
        >
          <BrandMark />
          <span className="brand-copy">
            Option Risk<small>포트폴리오 위험 분석</small>
          </span>
        </a>
        <nav className="workspace-nav" aria-label="주요 화면">
          {tabs.map((item, index) => (
            <button
              key={item}
              className={tab === item ? "active" : ""}
              aria-current={tab === item ? "page" : undefined}
              onClick={() => setTab(item)}
            >
              <NavigationIcon index={index} />
              <span>{item}</span>
            </button>
          ))}
        </nav>
        <div className="workspace-context">
          <div className="workspace-engine">
            <span>평가 엔진</span>
            <strong>
              Heston <em>+ MLP</em>
            </strong>
          </div>
          {session.data?.localDemoMode ? (
            <div className="logout">로컬 작업공간 · 자동 진입</div>
          ) : (
            <button
              className="logout"
              onClick={async () => {
                await api("logout/", {});
                setInputs(undefined);
                setSaved(undefined);
                setSelectedRun(undefined);
                client.clear();
                client.invalidateQueries();
              }}
            >
              로그아웃 · {session.data?.user?.username}
            </button>
          )}
        </div>
      </aside>
      <main className="main">
        <section className="page-heading">
          <div>
            <h1>
              {tab === "포지션"
                ? "포트폴리오 구성"
                : tab === "시장 · 시나리오"
                  ? "시장 · 시나리오"
                  : tab === "평가 · 실행 이력"
                    ? "평가 결과"
                    : "모델 검증"}
            </h1>
            <p className="muted">
              {tab === "포지션"
                ? "옵션 계약을 입력하고 평가에 사용할 버전을 저장합니다."
                : tab === "시장 · 시나리오"
                  ? "평가일을 고정하고 현물·초기 변동성·금리 충격을 설정합니다."
                  : tab === "평가 · 실행 이력"
                    ? "실행별 가격과 손익을 확인합니다. 불완전한 결과는 합산하지 않습니다."
                    : "ML 가격의 오차와 지원 범위를 확인합니다. 기준 평가와 민감도는 Heston 엔진을 사용합니다."}
            </p>
          </div>
        </section>
        {error && (
          <div className="error banner" role="alert">
            {error.message}
          </div>
        )}
        {notice && (
          <div className="notice banner" role="status">
            {notice}
          </div>
        )}
        {inputs && (tab === "포지션" || tab === "시장 · 시나리오") && (
          <>
            <div className="stats" role="group" aria-label="입력 요약">
              <div>
                <span>기초자산</span>
                <strong>
                  {inputs.market.underlying ?? "SYNTH_INDEX"}
                  <em>{inputs.market.currency ?? "USD"}</em>
                </strong>
              </div>
              <div>
                <span>평가일</span>
                <strong>
                  <time dateTime={inputs.market.valuation_date}>
                    {inputs.market.valuation_date || "—"}
                  </time>
                </strong>
              </div>
              <div>
                <span>포지션</span>
                <strong>
                  {inputs.positions.length}
                  <em> / 100</em>
                </strong>
              </div>
              <div>
                <span>시나리오</span>
                <strong>
                  {inputs.scenarios.length}
                  <em> / 100</em>
                </strong>
              </div>
              <div>
                <span>입력 버전</span>
                <strong className={`stat-word ${saved ? "saved" : "unsaved"}`}>
                  {saved ? "저장됨" : "미저장"}
                  {saved && <em>{saved.hash?.slice(0, 8)}</em>}
                </strong>
              </div>
            </div>
            <section
              className="panel input-toolbar"
              aria-label="포트폴리오 버전"
            >
              <label>
                포트폴리오 이름
                <input
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value);
                    setSaved(undefined);
                  }}
                />
              </label>
              <label>
                저장된 버전 열기
                <select
                  value={saved?.id ?? ""}
                  onChange={async (e) => {
                    if (!e.target.value) return;
                    const item = await api<InputVersion>(
                      `inputs/${e.target.value}/`,
                    );
                    setInputs(item.inputs);
                    setSaved(item);
                    setName(item.name);
                  }}
                >
                  <option value="">버전을 선택하세요</option>
                  {snapshots.data?.items.map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.name} · {item.hash.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="ghost"
                onClick={() => {
                  if (sample.data) {
                    edit(structuredClone(sample.data));
                    setNotice("합성 샘플 입력을 불러왔습니다.");
                  }
                }}
              >
                샘플 불러오기
              </button>
            </section>
            {tab === "포지션" ? (
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>
                      옵션 계약{" "}
                      <span className="count">{inputs.positions.length}</span>
                    </h2>
                    <p>유럽형 · 현금결제 · 무배당 · ACT/365F</p>
                  </div>
                  <div className="button-row">
                    <button
                      className="ghost"
                      onClick={() =>
                        downloadText(
                          "positions-template.csv",
                          "option_type,strike,expiry,side,quantity,multiplier\ncall,100,2027-11-08,long,10,100\nput,95,2027-05-08,short,-5,100\n",
                        )
                      }
                    >
                      CSV 템플릿
                    </button>
                    <label className="file-button">
                      CSV 가져오기
                      <input
                        type="file"
                        accept=".csv,text/csv"
                        onChange={async (e) => {
                          const file = e.target.files?.[0];
                          if (!file) return;
                          try {
                            edit({
                              ...inputs,
                              positions: parsePositionsCSV(await file.text()),
                            });
                            setNotice(
                              "CSV 포지션을 불러왔습니다. 저장 시 만기를 다시 검증합니다.",
                            );
                          } catch (err) {
                            setNotice((err as Error).message);
                          }
                          e.target.value = "";
                        }}
                      />
                    </label>
                  </div>
                </div>
                <div
                  className="table-scroll"
                  role="region"
                  aria-label="옵션 계약 표"
                  tabIndex={0}
                >
                  <table className="position-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>옵션 종류</th>
                        <th className="numeric">행사가</th>
                        <th>만기일</th>
                        <th>방향</th>
                        <th className="numeric">부호 있는 수량</th>
                        <th className="numeric">계약 승수</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {inputs.positions.map((position, index) => {
                        const change = (next: Position) =>
                          edit({
                            ...inputs,
                            positions: inputs.positions.map((item, i) =>
                              i === index ? next : item,
                            ),
                          });
                        return (
                          <tr
                            key={index}
                            data-side={position.side}
                            data-option={position.contract.option_type}
                          >
                            <td className="row-number">
                              {String(index + 1).padStart(2, "0")}
                            </td>
                            <td className="option-cell">
                              <select
                                aria-label={`옵션 종류 ${index + 1}`}
                                value={position.contract.option_type}
                                onChange={(e) =>
                                  change({
                                    ...position,
                                    contract: {
                                      ...position.contract,
                                      option_type: e.target.value as
                                        "call" | "put",
                                    },
                                  })
                                }
                              >
                                <option value="call">CALL</option>
                                <option value="put">PUT</option>
                              </select>
                            </td>
                            <td className="numeric">
                              <input
                                aria-label={`행사가 ${index + 1}`}
                                type="number"
                                step="any"
                                value={position.contract.strike}
                                onChange={(e) =>
                                  change({
                                    ...position,
                                    contract: {
                                      ...position.contract,
                                      strike: Number(e.target.value),
                                    },
                                  })
                                }
                              />
                            </td>
                            <td className="date-cell">
                              <input
                                aria-label={`만기일 ${index + 1}`}
                                type="date"
                                value={position.contract.expiry}
                                onChange={(e) =>
                                  change({
                                    ...position,
                                    contract: {
                                      ...position.contract,
                                      expiry: e.target.value,
                                    },
                                  })
                                }
                              />
                            </td>
                            <td className="side-cell">
                              <select
                                aria-label={`방향 ${index + 1}`}
                                value={position.side}
                                onChange={(e) =>
                                  change({
                                    ...position,
                                    side: e.target.value as "long" | "short",
                                    quantity:
                                      Math.abs(position.quantity) *
                                      (e.target.value === "long" ? 1 : -1),
                                  })
                                }
                              >
                                <option value="long">LONG +</option>
                                <option value="short">SHORT −</option>
                              </select>
                            </td>
                            <td className="numeric">
                              <input
                                aria-label={`수량 ${index + 1}`}
                                type="number"
                                step="1"
                                value={position.quantity}
                                onChange={(e) =>
                                  change({
                                    ...position,
                                    quantity: Number(e.target.value),
                                  })
                                }
                              />
                            </td>
                            <td className="numeric">
                              <input
                                aria-label={`승수 ${index + 1}`}
                                type="number"
                                step="any"
                                value={position.multiplier}
                                onChange={(e) =>
                                  change({
                                    ...position,
                                    multiplier: Number(e.target.value),
                                  })
                                }
                              />
                            </td>
                            <td>
                              <button
                                className="icon-button"
                                aria-label={`포지션 ${index + 1} 삭제`}
                                onClick={() =>
                                  edit({
                                    ...inputs,
                                    positions: inputs.positions.filter(
                                      (_, i) => i !== index,
                                    ),
                                  })
                                }
                              >
                                ×
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <button
                  className="add-row"
                  disabled={inputs.positions.length >= 100}
                  onClick={() =>
                    edit({
                      ...inputs,
                      positions: [
                        ...inputs.positions,
                        {
                          contract: {
                            option_type: "call",
                            strike: inputs.market.spot,
                            expiry:
                              sample.data?.positions[0].contract.expiry ??
                              "2027-11-08",
                          },
                          side: "long",
                          quantity: 1,
                          multiplier: 100,
                        },
                      ],
                    })
                  }
                >
                  ＋ 포지션 추가
                </button>
                <div className="panel-foot">
                  포지션 가치 = <b>부호 있는 수량 × 승수 × 옵션 단위 가격</b>
                  <button
                    className="text-button"
                    onClick={() => setTab("시장 · 시나리오")}
                  >
                    시장 · 시나리오 설정
                  </button>
                </div>
              </section>
            ) : (
              <>
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>시장 스냅샷</h2>
                      <p>고정 평가일 · 단일 금리 · 배당률 q = 0</p>
                    </div>
                    <span className="pill neutral">합성 시장 입력</span>
                  </div>
                  <div className="fields">
                    <label>
                      평가일
                      <input
                        type="date"
                        value={inputs.market.valuation_date}
                        onChange={(e) =>
                          edit({
                            ...inputs,
                            market: {
                              ...inputs.market,
                              valuation_date: e.target.value,
                            },
                          })
                        }
                      />
                    </label>
                    <NumberField
                      label="현물 지수"
                      value={inputs.market.spot}
                      onChange={(spot) =>
                        edit({ ...inputs, market: { ...inputs.market, spot } })
                      }
                    />
                    <NumberField
                      label="금리 · 연율 %"
                      value={inputs.market.rate * 100}
                      onChange={(v) =>
                        edit({
                          ...inputs,
                          market: { ...inputs.market, rate: v / 100 },
                        })
                      }
                    />
                    <NumberField
                      label="초기 변동성 σ₀ · 연율 %"
                      value={inputs.market.sigma0 * 100}
                      onChange={(v) =>
                        edit({
                          ...inputs,
                          market: { ...inputs.market, sigma0: v / 100 },
                        })
                      }
                    />
                  </div>
                  <div className="model-strip">
                    <b>고정 Heston 모형</b> κ {inputs.model.kappa}{" "}
                    <span>θ {inputs.model.theta}</span> ξ {inputs.model.xi}{" "}
                    <span>ρ {inputs.model.rho}</span>
                    <small>
                      초기 분산 v₀ = σ₀² = {money(inputs.market.sigma0 ** 2, 4)}
                    </small>
                  </div>
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>스트레스 시나리오</h2>
                      <p>현물 상대 % · 변동성 절대 %p · 금리 bp</p>
                    </div>
                    <button
                      className="ghost"
                      onClick={() =>
                        edit({
                          ...inputs,
                          scenarios: [
                            {
                              name: "base",
                              spot_shock_pct: 0,
                              sigma0_shock_pp: 0,
                              rate_shock_bp: 0,
                            },
                            {
                              name: "Equity sell-off",
                              spot_shock_pct: -10,
                              sigma0_shock_pp: 5,
                              rate_shock_bp: 0,
                            },
                            {
                              name: "Rate increase",
                              spot_shock_pct: 0,
                              sigma0_shock_pp: 0,
                              rate_shock_bp: 100,
                            },
                            {
                              name: "Risk-on",
                              spot_shock_pct: 10,
                              sigma0_shock_pp: -5,
                              rate_shock_bp: -50,
                            },
                          ],
                        })
                      }
                    >
                      프리셋 적용
                    </button>
                  </div>
                  <div
                    className="table-scroll"
                    role="region"
                    aria-label="스트레스 시나리오 표"
                    tabIndex={0}
                  >
                    <table className="scenario-table">
                      <thead>
                        <tr>
                          <th>시나리오</th>
                          <th className="numeric">현물 · %</th>
                          <th className="numeric">초기 변동성 · %p</th>
                          <th className="numeric">금리 · bp</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {inputs.scenarios.map((scenario, index) => {
                          const change = (next: Scenario) =>
                            edit({
                              ...inputs,
                              scenarios: inputs.scenarios.map((item, i) =>
                                i === index ? next : item,
                              ),
                            });
                          return (
                            <tr key={index}>
                              <td>
                                <input
                                  aria-label={`시나리오 이름 ${index + 1}`}
                                  value={scenario.name}
                                  onChange={(e) =>
                                    change({
                                      ...scenario,
                                      name: e.target.value,
                                    })
                                  }
                                />
                              </td>
                              {(
                                [
                                  "spot_shock_pct",
                                  "sigma0_shock_pp",
                                  "rate_shock_bp",
                                ] as const
                              ).map((field) => (
                                <td key={field} className="numeric">
                                  <input
                                    aria-label={`${field} ${index + 1}`}
                                    type="number"
                                    step="any"
                                    value={scenario[field]}
                                    onChange={(e) =>
                                      change({
                                        ...scenario,
                                        [field]: Number(e.target.value),
                                      })
                                    }
                                  />
                                </td>
                              ))}
                              <td>
                                <button
                                  className="icon-button"
                                  aria-label={`시나리오 ${index + 1} 삭제`}
                                  onClick={() =>
                                    edit({
                                      ...inputs,
                                      scenarios: inputs.scenarios.filter(
                                        (_, i) => i !== index,
                                      ),
                                    })
                                  }
                                >
                                  ×
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <button
                    className="add-row"
                    disabled={inputs.scenarios.length >= 100}
                    onClick={() =>
                      edit({
                        ...inputs,
                        scenarios: [
                          ...inputs.scenarios,
                          {
                            name: `Custom ${inputs.scenarios.length}`,
                            spot_shock_pct: 0,
                            sigma0_shock_pp: 0,
                            rate_shock_bp: 0,
                          },
                        ],
                      })
                    }
                  >
                    ＋ 시나리오 추가
                  </button>
                  <div className="panel-foot">
                    +5%p 변동성: σ₀ 20% → 25%, v₀ 0.04 → 0.0625. 평가일과
                    잔존만기는 유지합니다.
                  </div>
                </section>
              </>
            )}
            <section
              className="execution-bar"
              aria-label="입력 저장과 평가 실행"
            >
              <div>
                <h2 className="execution-title">
                  평가 실행{" "}
                  <span className={`pill ${saved ? "completed" : "neutral"}`}>
                    {saved ? "입력 저장됨" : "저장 필요"}
                  </span>
                </h2>
                <p>
                  {saved
                    ? "저장된 입력 버전을 사용합니다."
                    : "입력 버전을 저장한 뒤 실행할 수 있습니다."}
                </p>
              </div>
              <div className="button-row">
                <select
                  aria-label="실행 모드"
                  value={mode}
                  onChange={(e) => setMode(e.target.value)}
                >
                  <option value="REFERENCE">REFERENCE · Heston</option>
                  <option value="COMPARE">COMPARE · Heston + ML</option>
                </select>
                {mode === "COMPARE" && (
                  <select
                    aria-label="ML 모델 버전"
                    value={artifactId}
                    onChange={(e) => setArtifactId(e.target.value)}
                  >
                    <option value="">ML 모델 선택</option>
                    {artifacts.data?.items.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name ?? item.id.slice(0, 8)}
                      </option>
                    ))}
                  </select>
                )}
                <button
                  className="ghost"
                  onClick={() => save.mutate()}
                  disabled={save.isPending || !name.trim() || !!saved}
                >
                  입력 버전 저장
                </button>
                <button
                  className="primary"
                  onClick={() => launch.mutate()}
                  disabled={
                    !saved ||
                    launch.isPending ||
                    (mode === "COMPARE" && !artifactId)
                  }
                >
                  평가 실행
                </button>
              </div>
            </section>
          </>
        )}
        {tab === "평가 · 실행 이력" && (
          <div className="results-layout">
            <details className="panel history" open={!selectedRun}>
              <summary>
                실행 이력 <span>{runs.data?.items.length ?? 0}건</span>
                <small>
                  {selectedRun
                    ? `선택된 실행 ${selectedRun.slice(0, 8)}`
                    : "평가할 실행을 선택하세요"}
                </small>
              </summary>
              <div className="panel-heading">
                <h2>실행 이력</h2>
                <button
                  className="text-button"
                  aria-label="실행 이력 새로고침"
                  onClick={() => runs.refetch()}
                >
                  새로고침
                </button>
              </div>
              {!runs.data?.items.length && (
                <div className="empty">
                  아직 실행이 없습니다.
                  <br />
                  입력을 저장한 뒤 평가를 실행하세요.
                </div>
              )}
              {runs.data?.items.map((item) => (
                <button
                  className={`run-item ${selectedRun === item.id ? "selected" : ""}`}
                  key={item.id}
                  aria-pressed={selectedRun === item.id}
                  onClick={() => setSelectedRun(item.id)}
                >
                  <div>
                    <span className={`pill ${item.status.toLowerCase()}`}>
                      {statusLabel[item.status] ?? item.status}
                    </span>
                    <small>{item.mode}</small>
                  </div>
                  <strong>{item.id.slice(0, 8)}</strong>
                  <time dateTime={item.created_at}>
                    {new Date(item.created_at).toLocaleString("ko-KR")}
                  </time>
                </button>
              ))}
            </details>
            <div>
              {run.data ? (
                <>
                  <section className="panel">
                    <div className="panel-heading">
                      <div>
                        <h2>
                          평가 결과{" "}
                          <span
                            className={`pill ${run.data.status.toLowerCase()}`}
                          >
                            {statusLabel[run.data.status] ?? run.data.status}
                          </span>
                        </h2>
                        <p className="run-identity">
                          {run.data.mode} · 실행 {run.data.id.slice(0, 8)}
                        </p>
                        <p className="result-asof">
                          평가 기준일{" "}
                          <time
                            dateTime={
                              run.data.pinned_inputs?.market.valuation_date
                            }
                          >
                            {run.data.pinned_inputs?.market.valuation_date ??
                              "—"}
                          </time>
                        </p>
                      </div>
                      <div className="button-row">
                        <a
                          className="ghost"
                          href={`/api/runs/${run.data.id}/export/?format=json`}
                          download
                        >
                          JSON 다운로드
                        </a>
                        <a
                          className="ghost"
                          href={`/api/runs/${run.data.id}/export/?format=csv`}
                          download
                        >
                          CSV 다운로드
                        </a>
                        {!pending(run.data) && (
                          <button
                            className="ghost"
                            disabled={retry.isPending}
                            onClick={() => retry.mutate()}
                          >
                            동일 입력 재실행
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="progress-line">
                      <span>
                        {run.data.progress.completed} /{" "}
                        {run.data.progress.total} 셀 처리 · 실패{" "}
                        {run.data.progress.failed}
                      </span>
                      <progress
                        value={run.data.progress.completed}
                        max={run.data.progress.total || 1}
                      />
                    </div>
                    <p className="muted run-timing">
                      접수부터 완료까지 {money(run.data.elapsed_seconds, 3)}초 ·
                      큐 대기와 저장 포함
                    </p>
                    {run.data.error && (
                      <p className="error">{run.data.error}</p>
                    )}
                    <div
                      className="table-scroll"
                      role="region"
                      aria-label="시나리오별 평가 결과 표"
                      tabIndex={0}
                    >
                      <table className="totals-table">
                        <thead>
                          <tr>
                            <th>시나리오</th>
                            <th>완결성</th>
                            <th className="numeric">기준 가치 · USD</th>
                            <th className="numeric">스트레스 P&L</th>
                            {run.data.mode === "COMPARE" && (
                              <>
                                <th className="numeric">ML P&L</th>
                                <th className="numeric">P&L 차이</th>
                              </>
                            )}
                          </tr>
                        </thead>
                        <tbody>
                          {run.data.totals?.map((total) => (
                            <tr key={total.scenario_index}>
                              <td>{total.scenario_name}</td>
                              <td>
                                <span
                                  className={`pill ${total.complete ? "completed" : "neutral"}`}
                                >
                                  {total.complete ? "완료" : "불완전"}
                                </span>
                              </td>
                              <td className="numeric">{money(total.value)}</td>
                              <td
                                className={`numeric ${(total.pnl ?? 0) < 0 ? "negative" : "positive"}`}
                              >
                                {money(total.pnl)}
                              </td>
                              {run.data!.mode === "COMPARE" && (
                                <>
                                  <td className="numeric">
                                    {money(total.ml_pnl)}
                                  </td>
                                  <td className="numeric">
                                    {money(
                                      total.ml_pnl != null && total.pnl != null
                                        ? total.ml_pnl - total.pnl
                                        : null,
                                    )}
                                  </td>
                                </>
                              )}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <Suspense fallback={<p className="muted">차트 준비 중…</p>}>
                      <StressChart totals={run.data.totals ?? []} />
                    </Suspense>
                  </section>
                  <section className="panel">
                    <div className="panel-heading">
                      <div>
                        <h2>포지션별 결과</h2>
                        <p>
                          민감도는 단위 옵션 기준. 초기 변동성 민감도는 1%p 변화
                          단위로 표시합니다.
                        </p>
                      </div>
                    </div>
                    <div
                      className="table-scroll"
                      role="region"
                      aria-label="포지션별 평가 결과 표"
                      tabIndex={0}
                    >
                      <table className="valuation-table">
                        <thead>
                          <tr>
                            <th>시나리오 / 포지션</th>
                            <th className="numeric">단위 가격</th>
                            <th className="numeric">포지션 가치</th>
                            <th className="numeric">Delta</th>
                            <th className="numeric">Gamma</th>
                            <th className="numeric">
                              초기 변동성 민감도 / 1%p
                            </th>
                            {run.data.mode === "COMPARE" && (
                              <th className="numeric">ML 단위 가격 / 사유</th>
                            )}
                            <th>상태 / 사유</th>
                          </tr>
                        </thead>
                        <tbody>
                          {run.data.results?.map((cell) => (
                            <tr
                              key={`${cell.scenario_index}-${cell.position_index}`}
                            >
                              <td>
                                {cell.scenario_name}
                                <small className="block">
                                  포지션 {cell.position_index + 1}
                                </small>
                              </td>
                              <td className="numeric">
                                {money(cell.reference_price, 4)}
                              </td>
                              <td className="numeric">
                                {money(cell.reference_value)}
                              </td>
                              <td className="numeric">
                                {money(cell.sensitivities?.delta, 4)}
                              </td>
                              <td className="numeric">
                                {money(cell.sensitivities?.gamma, 6)}
                              </td>
                              <td className="numeric">
                                {money(
                                  cell.sensitivities
                                    ?.initial_volatility_sensitivity != null
                                    ? cell.sensitivities
                                        .initial_volatility_sensitivity * 0.01
                                    : null,
                                  4,
                                )}
                              </td>
                              {run.data!.mode === "COMPARE" && (
                                <td className="numeric ml-result">
                                  {money(cell.ml_price, 4)}
                                  <small className="block">
                                    가격 차이 {money(cell.price_error, 4)}
                                  </small>
                                  <small className="block">
                                    기준{" "}
                                    {money(
                                      cell.timings?.reference_seconds == null
                                        ? null
                                        : cell.timings.reference_seconds * 1000,
                                      3,
                                    )}{" "}
                                    ms
                                    {" / ML "}
                                    {money(
                                      cell.timings?.ml_seconds == null
                                        ? null
                                        : cell.timings.ml_seconds * 1000,
                                      3,
                                    )}{" "}
                                    ms
                                  </small>
                                  {cell.ml_error && (
                                    <small className="error block">
                                      {cell.ml_error}
                                    </small>
                                  )}
                                </td>
                              )}
                              <td
                                className={
                                  cell.error ? "error" : "result-status"
                                }
                              >
                                {cell.error ||
                                  (statusLabel[cell.status] ?? cell.status)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                  <details className="panel provenance">
                    <summary>입력 · 계산 출처 보기</summary>
                    <p className="muted">
                      실행 시각:{" "}
                      <time dateTime={run.data.created_at}>
                        {new Date(run.data.created_at).toLocaleString("ko-KR")}
                      </time>
                    </p>
                    <p className="muted">
                      같은 입력과 모델 버전으로 수치 허용오차 안에서 재현합니다.
                    </p>
                    <pre>
                      {JSON.stringify(
                        {
                          provenance: run.data.provenance,
                          inputs: run.data.pinned_inputs,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </>
              ) : (
                <section className="panel empty">
                  <h2>실행을 선택하세요</h2>
                  <p>
                    실행 이력에서 가격·민감도와 저장된 계산 출처를 확인할 수
                    있습니다.
                  </p>
                </section>
              )}
            </div>
          </div>
        )}
        {tab === "ML 검증" && (
          <>
            <section className="comparison-intro">
              <div>
                <h2>Heston 기준 모델과 MLP 비교</h2>
                <p>
                  Heston의 준해석적 가격으로 학습합니다. 지원 영역 밖에서는 ML
                  결과 대신 사유를 표시하고 기준 가격을 유지합니다.
                </p>
              </div>
              <div className="flow" aria-label="ML 입력과 출력">
                <span>입력: log(S/K) · T · r · σ₀</span>
                <span>출력: C / K</span>
              </div>
            </section>
            {!artifacts.data?.items.length && (
              <section className="panel empty">
                <h2>등록된 모델이 없습니다.</h2>
                <p>
                  오프라인 학습·검증 후 모델을 등록하면 지원 영역과 검증
                  보고서가 표시됩니다.
                </p>
              </section>
            )}
            {reportArtifact && (
              <>
                <div className="report-toolbar">
                  <label>
                    검증 보고서 모델
                    <select
                      value={reportArtifact.id}
                      onChange={(e) => setSelectedReportId(e.target.value)}
                    >
                      {artifacts.data?.items.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name ?? "ML 가격 모델"} · {item.id.slice(0, 8)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <span className="muted">
                    {artifacts.data?.items.length ?? 0}개 등록 버전
                  </span>
                </div>
                <section className="panel" key={reportArtifact.id}>
                  <div className="panel-heading">
                    <div>
                      <h2>{reportArtifact.name ?? "ML 가격 모델"}</h2>
                      <p className="artifact-id">
                        모델 ID · {reportArtifact.id}
                      </p>
                    </div>
                    <button
                      className="primary"
                      onClick={() => {
                        setArtifactId(reportArtifact.id);
                        setMode("COMPARE");
                        setTab("시장 · 시나리오");
                      }}
                    >
                      이 모델로 비교
                    </button>
                  </div>
                  <ModelSummary artifact={reportArtifact} />
                </section>
              </>
            )}
          </>
        )}
        <footer>
          <span>유럽형 옵션 · USD · ACT/365F</span>
          <span>결정론적 스트레스 · VaR/ES 제외</span>
        </footer>
      </main>
    </div>
  );
}
