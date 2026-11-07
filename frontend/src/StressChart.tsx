import { useEffect, useRef } from "react";
import type { Total } from "./types";

const compactName = (name: string, limit: number) => {
  const letters = Array.from(name);
  return letters.length > limit
    ? `${letters.slice(0, limit - 1).join("")}…`
    : name;
};

export default function StressChart({ totals }: { totals: Total[] }) {
  const root = useRef<HTMLDivElement>(null);
  const useBars = totals.length <= 8;

  useEffect(() => {
    const element = root.current;
    if (!element) return;

    let disposed = false;
    let plotly: (typeof import("plotly.js-dist-min"))["default"] | undefined;
    let observer: ResizeObserver | undefined;
    let frame = 0;
    let previousWidth = 0;
    const valid = totals.filter(
      (row): row is Total & { pnl: number } =>
        row.complete && row.pnl !== null && Number.isFinite(row.pnl),
    );
    const omitted = totals.length - valid.length;
    const extent = Math.max(0, ...valid.map((row) => Math.abs(row.pnl))) || 1;
    const names = valid.map((row) => row.scenario_name);
    const mono = '"Cascadia Code", "SFMono-Regular", Consolas, monospace';
    const digits = Math.min(6, Math.max(2, Math.ceil(-Math.log10(extent)) + 1));
    const numberFormat = `,.${digits}f`;

    import("plotly.js-dist-min").then(({ default: Plotly }) => {
      if (disposed) return;
      plotly = Plotly;

      const draw = () => {
        const width = element.clientWidth;
        if (disposed || width <= 0 || width === previousWidth) return;
        previousWidth = width;
        const narrow = width < 600;
        const labelCount = Math.max(1, Math.floor((width - 90) / 120));
        const stride = Math.max(1, Math.ceil(valid.length / labelCount));
        const ticks = names.filter((_, index) => index % stride === 0);
        const annotations = [];
        if (!valid.length) {
          annotations.push({
            text: "완료된 시나리오가 아직 없습니다.",
            x: 0.5,
            y: 0.5,
            xref: "paper",
            yref: "paper",
            showarrow: false,
            font: { size: 13, color: "#64748b" },
          });
        } else if (omitted) {
          annotations.push({
            text: `미완료 시나리오 ${omitted}개 제외`,
            x: 1,
            y: 1,
            yshift: 20,
            xanchor: "right",
            xref: "paper",
            yref: "paper",
            showarrow: false,
            font: { size: 12, color: "#64748b" },
          });
        }

        const trace = useBars
          ? {
              type: "bar",
              orientation: "h",
              x: valid.map((row) => row.pnl),
              y: names,
              customdata: names,
              marker: {
                color: valid.map((row) =>
                  row.pnl < 0 ? "#cc5d52" : row.pnl > 0 ? "#315edb" : "#94a3b8",
                ),
                line: { width: 0 },
              },
              width: 0.48,
              text: valid.map((row) =>
                row.pnl.toLocaleString("en-US", {
                  minimumFractionDigits: digits,
                  maximumFractionDigits: digits,
                }),
              ),
              textposition: narrow ? "auto" : "outside",
              textfont: { family: mono, size: 12 },
              insidetextfont: { color: "#ffffff" },
              outsidetextfont: { color: "#334155" },
              cliponaxis: false,
              hovertemplate: `%{customdata}<br>%{x:${numberFormat}} USD<extra></extra>`,
            }
          : {
              type: "heatmap",
              x: names,
              y: ["Stress P&L · USD"],
              z: [valid.map((row) => row.pnl)],
              customdata: [names],
              zauto: false,
              zmin: -extent,
              zmax: extent,
              zmid: 0,
              colorscale: [
                [0, "#cc5d52"],
                [0.5, "#f1f5f9"],
                [1, "#315edb"],
              ],
              xgap: valid.length <= 30 ? 2 : 0,
              hovertemplate: `%{customdata}<br>%{z:${numberFormat}} USD<extra></extra>`,
              colorbar: {
                title: { text: "USD", side: "top", font: { size: 12 } },
                thickness: 8,
                outlinewidth: 0,
                tickvals: [-extent, 0, extent],
                tickformat: extent < 1 ? `.${digits}f` : ",.0f",
                tickfont: { family: mono, size: 12 },
                len: 0.9,
              },
            };

        void Plotly.react(
          element,
          valid.length ? [trace] : [],
          {
            width,
            height: useBars ? Math.max(192, valid.length * 48 + 80) : 192,
            margin: useBars
              ? { l: narrow ? 100 : 180, r: narrow ? 20 : 36, t: 32, b: 48 }
              : { l: 8, r: 84, t: 32, b: 48 },
            paper_bgcolor: "transparent",
            plot_bgcolor: "transparent",
            font: { family: "system-ui", size: 13, color: "#334155" },
            hoverlabel: {
              bgcolor: "#172337",
              bordercolor: "#172337",
              font: { family: mono, size: 12, color: "#ffffff" },
              align: "left",
            },
            yaxis: useBars
              ? {
                  type: "category",
                  categoryorder: "array",
                  categoryarray: names,
                  autorange: "reversed",
                  tickmode: "array",
                  tickvals: names,
                  ticktext: names.map((name) =>
                    compactName(name, narrow ? 12 : 24),
                  ),
                  tickfont: { size: 12, color: "#475569" },
                  showgrid: false,
                  zeroline: false,
                  fixedrange: true,
                  visible: valid.length > 0,
                }
              : {
                  showticklabels: false,
                  fixedrange: true,
                  visible: valid.length > 0,
                },
            xaxis: useBars
              ? {
                  range: [-extent * 1.35, extent * 1.35],
                  nticks: narrow ? 3 : 5,
                  tickformat: extent < 1 ? `.${digits}f` : ",.0f",
                  tickfont: { family: mono, size: 12, color: "#64748b" },
                  title: {
                    text: "Stress P&L · USD",
                    font: { size: 12 },
                    standoff: 10,
                  },
                  gridcolor: "#e7edf5",
                  zeroline: true,
                  zerolinecolor: "#94a3b8",
                  zerolinewidth: 1,
                  fixedrange: true,
                  visible: valid.length > 0,
                }
              : {
                  tickmode: "array",
                  tickvals: ticks,
                  ticktext: ticks.map((name) => compactName(name, 16)),
                  tickangle: 0,
                  tickfont: { size: 12, color: "#475569" },
                  fixedrange: true,
                  visible: valid.length > 0,
                },
            annotations,
          },
          { responsive: false, displayModeBar: false },
        );
      };

      draw();
      observer = new ResizeObserver(() => {
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(draw);
      });
      observer.observe(element);
    });
    return () => {
      disposed = true;
      observer?.disconnect();
      cancelAnimationFrame(frame);
      plotly?.purge(element);
    };
  }, [totals, useBars]);

  return (
    <div
      ref={root}
      className="stress-chart"
      aria-label={`완료된 시나리오 스트레스 손익 ${useBars ? "막대그래프 · USD · 0 중심 대칭 축" : "히트맵 · USD · 0 중심 대칭 색상"}`}
    />
  );
}
