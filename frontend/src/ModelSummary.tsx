import type { Artifact } from "./types";

type Errors = {
  count: number;
  mean: number;
  maximum: number;
  p95: number;
  p99: number;
};
type Report = {
  all_normalized_errors: Errors;
  splits: Record<string, { usd_call_error_at_strike_100: Errors }>;
  portfolio_stress_pnl: { usd_error: Errors; portfolio_count: number };
  timing: { case_count: number; median: Record<string, number> };
};
const value = (n: number | undefined, digits = 4) =>
  n == null
    ? "—"
    : n.toLocaleString("en-US", {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      });
export default function ModelSummary({ artifact }: { artifact: Artifact }) {
  const domain = artifact.manifest.domain as Record<string, [number, number]>;
  const validation = artifact.manifest.validation as {
    status: string;
    gates: Record<string, number>;
  };
  const report = artifact.validation_report as Report | null | undefined;
  const labels: Record<string, string> = {
    log_moneyness: "log(S/K)",
    maturity_years: "잔존만기 · 년",
    rate: "금리 · 연율 소수",
    sigma0: "초기 변동성 · 연율 소수",
  };
  return (
    <div className="model-document">
      <p className="model-note">
        지원 영역을 벗어나거나 고정 Heston 모델이 다르면 ML 가격을 제공하지
        않습니다. Put은 call 가격으로부터 parity로 계산합니다.
      </p>
      <div className="domain-strip">
        {Object.entries(domain ?? {}).map(([key, range]) => (
          <div key={key}>
            <span>{labels[key] ?? key}</span>
            <strong className="numeric domain-range">
              {value(range[0], 3)} ~ {value(range[1], 3)}
            </strong>
          </div>
        ))}
      </div>
      <p className="model-note model-status">
        <span
          className={`pill ${validation?.status === "passed" ? "completed" : "failed"}`}
        >
          {validation?.status === "passed"
            ? "비교용 기준 통과"
            : "검증 기준 미통과"}
        </span>{" "}
        정확도 기준은 초기 실측 후 설정했으며 공식 위험 계산 승인을 의미하지
        않습니다.
      </p>
      {artifact.report_error && (
        <p className="error">
          검증 보고서를 확인할 수 없습니다: {artifact.report_error}
        </p>
      )}
      {report && (
        <>
          <h2>가격 오차 · USD</h2>
          <p className="model-note">
            행사가 100 기준 절대 오차. 독립 검증{" "}
            {report.all_normalized_errors.count.toLocaleString("en-US")}건.
          </p>
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="ML 가격 오차 표"
          >
            <table className="model-table">
              <thead>
                <tr>
                  <th>영역</th>
                  <th className="numeric">표본</th>
                  <th className="numeric">평균</th>
                  <th className="numeric">P95</th>
                  <th className="numeric">P99</th>
                  <th className="numeric">최대</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(report.splits).map(([name, split]) => {
                  const e = split.usd_call_error_at_strike_100;
                  return (
                    <tr key={name}>
                      <td>
                        {(
                          {
                            random: "무작위",
                            heldout: "학습에서 제외한 영역",
                            edge: "만기·ITM/OTM·영역 경계",
                          } as Record<string, string>
                        )[name] ?? name}
                      </td>
                      <td className="numeric">
                        {e.count.toLocaleString("en-US")}
                      </td>
                      <td className="numeric">{value(e.mean)}</td>
                      <td className="numeric">{value(e.p95)}</td>
                      <td className="numeric">{value(e.p99)}</td>
                      <td className="numeric">{value(e.maximum)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="model-note">
            포트폴리오{" "}
            {report.portfolio_stress_pnl.portfolio_count.toLocaleString(
              "en-US",
            )}
            개 스트레스 P&L: 평균 오차 $
            {value(report.portfolio_stress_pnl.usd_error.mean, 2)}, 최대 $
            {value(report.portfolio_stress_pnl.usd_error.maximum, 2)}.
          </p>
          <h2>실행 시간 · ms</h2>
          <p className="model-note">
            같은 {report.timing.case_count.toLocaleString("en-US")}건의 워밍업
            후 중앙값 · CPU · 재사용 기준 엔진. API·큐 대기 시간은 제외합니다.
          </p>
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="ML 실행 시간 표"
          >
            <table className="model-table">
              <thead>
                <tr>
                  <th>경로</th>
                  <th className="numeric">시간</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(report.timing.median).map(([key, time]) => (
                  <tr key={key}>
                    <td>
                      {(
                        {
                          reference_reused: "Heston 기준 엔진 재사용",
                          ml_batch_with_validation: "ML 배치 + 입력 검증",
                          ml_per_position_with_validation:
                            "ML 개별 호출 + 입력 검증",
                          ml_tensor_core: "ML 텐서 계산만",
                        } as Record<string, string>
                      )[key] ?? key}
                    </td>
                    <td className="numeric">{value(time * 1000, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="model-note">
            현재 워커는 개별 호출 경로를 사용합니다. 배치 성능을 실제 실행의
            속도 향상으로 해석하지 않습니다.
          </p>
        </>
      )}
      <details>
        <summary>지원 조건·검증 기준·재현 정보</summary>
        <pre
          tabIndex={0}
          role="region"
          aria-label="모델 지원 조건 및 재현 정보 JSON"
        >
          {JSON.stringify(artifact.manifest, null, 2)}
        </pre>
      </details>
    </div>
  );
}
