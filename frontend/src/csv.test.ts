import { describe, expect, it } from "vitest";
import { parsePositionsCSV } from "./csv";
const header = "option_type,strike,expiry,side,quantity,multiplier\n";
describe("CSV position boundary", () => {
  it("preserves signed shorts and quoted fields", () => {
    const [position] = parsePositionsCSV(
      header + '"put",100,2027-11-08,short,-5,100',
    );
    expect(position.quantity).toBe(-5);
    expect(position.contract.option_type).toBe("put");
  });
  it.each([
    "call,100,2027-11-08,short,5,100",
    "call,100,2027-02-30,long,1,100",
    "call,,2027-11-08,long,1,100",
    "call,Infinity,2027-11-08,long,1,100",
    "call,100,2027-11-08,long,0.5,100",
  ])("rejects invalid input: %s", (row) =>
    expect(() => parsePositionsCSV(header + row)).toThrow(),
  );
  it("rejects unknown columns and over-cap batches", () => {
    expect(() =>
      parsePositionsCSV(
        header.replace("strike", "price") + "call,100,2027-11-08,long,1,100",
      ),
    ).toThrow();
    expect(() =>
      parsePositionsCSV(
        header + Array(101).fill("call,100,2027-11-08,long,1,100").join("\n"),
      ),
    ).toThrow();
  });
});
