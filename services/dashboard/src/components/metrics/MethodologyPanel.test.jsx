// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §20.3 -- the G-class
// "intentional omission" values are present, addressable and testable in a
// collapsed-by-default panel.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import real from "../../__fixtures__/realArtifact.js";
import { parseArtifact } from "../../lib/d6Contract.js";
import { buildMetricsModel } from "../../lib/metricsModel.js";
import MethodologyPanel from "./MethodologyPanel.jsx";

const m = buildMetricsModel(parseArtifact(real));
const renderPanel = () =>
  render(
    <MethodologyPanel
      provenance={m.provenance}
      block3={m.block3}
      block5={m.block5}
      tierE={m.tierE}
    />,
  );

describe("MethodologyPanel", () => {
  it("is collapsed by default", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: /Methodology & provenance/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByTestId("methodology-body")).toBeNull();
  });

  it("on expand, the G-class omissions and identity values are addressable", async () => {
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /Methodology & provenance/ }));
    const body = screen.getByTestId("methodology-body");
    expect(body).toHaveTextContent("fixture_sha256");
    expect(body).toHaveTextContent(real.provenance.fixture_sha256.slice(0, 16));
    expect(body).toHaveTextContent("calibrator_version");
    expect(body).toHaveTextContent("platt-v1");
    expect(body).toHaveTextContent("build_hash");
    expect(body).toHaveTextContent("corpus_db_sha256");
    expect(body).toHaveTextContent("model_files_sha256[audit.json]");
    expect(body).toHaveTextContent("generation_command");
    expect(body).toHaveTextContent("n_bins");
    expect(body).toHaveTextContent("distinct_cards");
    expect(body).toHaveTextContent("286");
    expect(body).toHaveTextContent("episode_duration_s");
    expect(body).toHaveTextContent("704");
    expect(body).toHaveTextContent("amount_quantile_band");
    expect(body).toHaveTextContent("[0, 26]");
    expect(body).toHaveTextContent("temporal_test");
    expect(body).toHaveTextContent("tier_e");
  });
});
