export type Position = {
  contract: {
    option_type: "call" | "put";
    strike: number;
    expiry: string;
    underlying?: string;
    currency?: string;
  };
  side: "long" | "short";
  quantity: number;
  multiplier: number;
};
export type Scenario = {
  name: string;
  spot_shock_pct: number;
  sigma0_shock_pp: number;
  rate_shock_bp: number;
};
export type Inputs = {
  market: {
    valuation_date: string;
    spot: number;
    rate: number;
    sigma0: number;
    underlying?: string;
    currency?: string;
  };
  model: { kappa: number; theta: number; xi: number; rho: number };
  positions: Position[];
  scenarios: Scenario[];
};
export type InputVersion = {
  id: string;
  name: string;
  inputs: Inputs;
  hash: string;
  version_ids: Record<string, string>;
};
export type Cell = {
  scenario_index: number;
  scenario_name: string;
  position_index: number;
  status: string;
  reference_price: number | null;
  reference_value: number | null;
  error: string;
  sensitivities: Record<string, number> | null;
  ml_price: number | null;
  ml_value: number | null;
  ml_error: string;
  timings?: { reference_seconds?: number; ml_seconds?: number };
  price_error?: number | null;
};
export type Total = {
  scenario_index: number;
  scenario_name: string;
  complete: boolean;
  value: number | null;
  pnl: number | null;
  ml_complete: boolean;
  ml_value: number | null;
  ml_pnl: number | null;
};
export type Run = {
  id: string;
  status: string;
  mode: string;
  created_at: string;
  progress: { completed: number; total: number; failed: number };
  results?: Cell[];
  totals?: Total[];
  pinned_inputs?: Inputs;
  provenance?: Record<string, unknown>;
  error?: string;
  elapsed_seconds?: number | null;
};
export type Artifact = {
  id: string;
  name?: string;
  manifest: Record<string, unknown>;
  hash?: string;
  validation_report?: Record<string, unknown> | null;
  report_error?: string | null;
};
