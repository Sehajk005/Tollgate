// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §17.2 / §23.6 FE-T-PROV-01..08.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import real from "../../__fixtures__/realArtifact.js";
import { withConfigMismatch } from "../../__fixtures__/synthetic.js";
import { parseArtifact } from "../../lib/d6Contract.js";
import { buildMetricsModel } from "../../lib/metricsModel.js";
import ProvenanceHeader from "./ProvenanceHeader.jsx";

const REAL_HASH = real.provenance.config_hash;

function renderHeader(artifact = real, currentConfigHash) {
  const m = buildMetricsModel(parseArtifact(artifact), { currentConfigHash });
  return render(
    <ProvenanceHeader
      provenance={m.provenance}
      freshness={m.freshness}
      primarySplit={m.block4.split}
    />,
  );
}

describe("FE-T-PROV: the six Eval §9 attributes + seeds_used, without interaction", () => {
  it("renders seed, config_hash, model_version, policy_version, π_eval, split, seeds_used", () => {
    renderHeader();
    const line = screen.getByTestId("prov-identity");
    expect(line).toHaveTextContent("seed 42");
    expect(line).toHaveTextContent(`config ${REAL_HASH.slice(0, 12)}`);
    expect(line).toHaveTextContent("model l1-lgbm-v1");
    expect(line).toHaveTextContent("policy 1");
    expect(line).toHaveTextContent("π_eval 0.01");
    expect(line).toHaveTextContent("split temporal_test");
    expect(line).toHaveTextContent("seeds_used 1");
  });

  it("renders generated_at as a human UTC date", () => {
    renderHeader();
    expect(screen.getByText(/generated 2026-09-02 17:03 UTC/)).toBeInTheDocument();
  });
});

describe("FE-T-PROV: three freshness states", () => {
  it("config-mismatch -> a visible warning with both hash prefixes", () => {
    renderHeader(withConfigMismatch(), REAL_HASH);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/Configs have changed since this evaluation/);
    expect(alert).toHaveTextContent("000000000000");
    expect(alert).toHaveTextContent(REAL_HASH.slice(0, 12));
  });

  it("matching hash -> neutral 'configs unchanged', no warning", () => {
    renderHeader(real, REAL_HASH);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(/configs unchanged since/)).toBeInTheDocument();
  });

  it("unknown (no injected hash) -> 'not verifiable', and never the word 'current'", () => {
    const { container } = renderHeader(real, undefined);
    expect(screen.getByText(/freshness not verifiable in this build/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container.textContent).not.toMatch(/\bcurrent\b/);
  });
});
