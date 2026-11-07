import Papa from "papaparse";
import type { Position } from "./types";

const fields = [
  "option_type",
  "strike",
  "expiry",
  "side",
  "quantity",
  "multiplier",
];
export function parsePositionsCSV(text: string): Position[] {
  const parsed = Papa.parse<Record<string, string>>(text, {
    header: true,
    skipEmptyLines: "greedy",
  });
  if (parsed.errors.length) throw new Error(`CSV: ${parsed.errors[0].message}`);
  if (
    parsed.meta.fields?.length !== fields.length ||
    !fields.every((f) => parsed.meta.fields?.includes(f))
  ) {
    throw new Error(`CSV 열은 ${fields.join(", ")} 이어야 합니다.`);
  }
  if (!parsed.data.length || parsed.data.length > 100)
    throw new Error("포지션은 1~100개여야 합니다.");
  return parsed.data.map((row, i) => {
    const number = (field: string) => {
      if (
        !row[field]?.trim() ||
        !/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(row[field].trim())
      )
        throw new Error(`${i + 2}행 ${field}: 숫자가 필요합니다.`);
      const value = Number(row[field]);
      if (!Number.isFinite(value))
        throw new Error(`${i + 2}행 ${field}: 유한한 숫자가 필요합니다.`);
      return value;
    };
    if (
      !["call", "put"].includes(row.option_type) ||
      !["long", "short"].includes(row.side)
    )
      throw new Error(`${i + 2}행: call/put, long/short를 확인하세요.`);
    const strike = number("strike"),
      quantity = number("quantity"),
      multiplier = number("multiplier");
    if (
      strike <= 0 ||
      multiplier <= 0 ||
      !Number.isSafeInteger(quantity) ||
      quantity === 0 ||
      (row.side === "long") !== quantity > 0
    )
      throw new Error(
        `${i + 2}행: 행사가·승수는 양수, 수량은 방향과 일치하는 정수여야 합니다.`,
      );
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(row.expiry) ||
      Number.isNaN(Date.parse(row.expiry)) ||
      new Date(row.expiry).toISOString().slice(0, 10) !== row.expiry
    )
      throw new Error(`${i + 2}행: 유효한 YYYY-MM-DD 만기일이 필요합니다.`);
    return {
      contract: {
        option_type: row.option_type as "call" | "put",
        strike,
        expiry: row.expiry,
      },
      side: row.side as "long" | "short",
      quantity,
      multiplier,
    };
  });
}

export function downloadText(name: string, content: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
