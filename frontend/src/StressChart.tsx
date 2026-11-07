import { useEffect, useRef } from "react";
import type { Total } from "./types";

export default function StressChart({ totals }: { totals: Total[] }) {
  const root = useRef<HTMLDivElement>(null);
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
    const extent = Math.max(0, ...valid.map((row) => Math.abs(row.pnl))) || 1;
    const names = valid.map((row) => row.scenario_name);
    const mono = '"IBM Plex Mono", "SFMono-Regular", Consolas, monospace';

    import("plotly.js-dist-min").then(({ default: Plotly }) => {
      if (disposed) return;
      plotly = Plotly;

      const draw = () => {
        const width = element.clientWidth;
        if (disposed || width <= 0 || width === previousWidth) return;
        previousWidth = width;
        const labelCount = Math.max(1, Math.floor((width - 80) / 100));
        const stride = Math.max(1, Math.ceil(valid.length / labelCount));
        const ticks = names.filter((_, index) => index % stride === 0);
        const digits = Math.min(
          6,
          Math.max(0, Math.ceil(-Math.log10(extent)) + 1),
        );

        void Plotly.react(
          element,
          valid.length
            ? [
                {
                  type: "heatmap",
                  x: names,
                  y: ["Stress P&L · USD"],
                  z: [valid.map((row) => row.pnl)],
                  zauto: false,
                  zmin: -extent,
                  zmax: extent,
                  zmid: 0,
                  colorscale: [
                    [0, "#b74735"],
                    [0.5, "#f0f0eb"],
                    [1, "#267061"],
                  ],
                  xgap: valid.length <= 30 ? 2 : 0,
                  hovertemplate: "%{x}<br>%{z:,.2f} USD<extra></extra>",
                  colorbar: {
                    title: { text: "USD", side: "top", font: { size: 10 } },
                    thickness: 8,
                    outlinewidth: 0,
                    tickvals: [-extent, 0, extent],
                    tickformat: extent < 1 ? `.${digits}f` : ",.0f",
                    tickfont: { family: mono, size: 10 },
                    len: 0.9,
                  },
                },
              ]
            : [],
          {
            width,
            height: 176,
            margin: { l: 8, r: 72, t: 12, b: 48 },
            paper_bgcolor: "transparent",
            plot_bgcolor: "transparent",
            font: { family: "system-ui", size: 11, color: "#202830" },
            hoverlabel: {
              bgcolor: "#202830",
              bordercolor: "#202830",
              font: { family: mono, size: 11, color: "#ffffff" },
            },
            yaxis: {
              showticklabels: false,
              fixedrange: true,
              visible: valid.length > 0,
            },
            xaxis: {
              tickmode: "array",
              tickvals: ticks,
              ticktext: ticks.map((name) => {
                const letters = Array.from(name);
                return letters.length > 15
                  ? `${letters.slice(0, 14).join("")}…`
                  : name;
              }),
              tickangle: 0,
              tickfont: { size: 10, color: "#52606c" },
              fixedrange: true,
              visible: valid.length > 0,
            },
            annotations: valid.length
              ? []
              : [
                  {
                    text: "완료된 시나리오가 아직 없습니다.",
                    x: 0.5,
                    y: 0.5,
                    xref: "paper",
                    yref: "paper",
                    showarrow: false,
                    font: { size: 11, color: "#52606c" },
                  },
                ],
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
  }, [totals]);
  return (
    <div
      ref={root}
      className="stress-chart"
      aria-label="완료된 시나리오 스트레스 손익 히트맵 · USD · 0 중심 대칭 색상"
    />
  );
}
