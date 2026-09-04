import { useCallback, useEffect, useState } from "react";

import NarrativeBlock from "../components/NarrativeBlock.jsx";
import ConfirmButton from "../components/ConfirmButton.jsx";
import DetectionTimeline from "../components/DetectionTimeline.jsx";
import ContributionBars from "../components/ContributionBars.jsx";
import EntityTable from "../components/EntityTable.jsx";
import AuditTrail from "../components/AuditTrail.jsx";
import ClientEvidencePanel from "../components/ClientEvidencePanel.jsx";
import { THREAT_TOKENS } from "../lib/labels.js";

// Day 8, Step 7 -- D3 Incident Detail (App Flow SS5 D3, "the centre of
// gravity"). Five stacked sections, in the spec's order:
//   1. narrative        2. action bar        3. evidence
//   4. audit trail      5. collapsed client-asserted panel
//
// The incident header fields already arriving on the SSE event drive the live
// top-of-screen state without a refetch (ThreatBand / SystemBanner / rail are
// in the shell). This screen fetches the full read model from
// GET /v1/incidents/{id} and never re-derives anything.

const API_KEY = import.meta.env.VITE_TOLLGATE_API_KEY || "";
const INCIDENT_THREAT = { OPEN: "elevated", ESCALATED: "under_attack", COOLING: "resolved", CLOSED: "calm" };

function Section({ title, children }) {
  return (
    <section style={{ marginBottom: 24 }}>
      <h2 className="tg-label" style={{ color: "var(--tg-text-mute)", margin: "0 0 8px" }}>{title}</h2>
      {children}
    </section>
  );
}

export default function D3Incident({ incidentId }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!incidentId) {
      setDetail(null);
      return;
    }
    try {
      const resp = await fetch(`/v1/incidents/${incidentId}`, { headers: { "X-Tollgate-Key": API_KEY } });
      if (!resp.ok) {
        setError(`HTTP ${resp.status}`);
        return;
      }
      setDetail(await resp.json());
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }, [incidentId]);

  useEffect(() => { load(); }, [load]);

  async function act(path, body) {
    setBusy(true);
    setError(null);
    try {
      const resp = await fetch(`/v1/incidents/${incidentId}/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Tollgate-Key": API_KEY },
        body: JSON.stringify(body),
      });
      if (!resp.ok) setError(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
      else await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!incidentId) {
    return (
      <div style={{ padding: 24 }}>
        <p className="tg-body" style={{ color: "var(--tg-text-2)" }}>
          No incidents. Baseline learned while traffic is nominal — the Incidents view opens the
          newest live incident the moment one fires.
        </p>
      </div>
    );
  }

  if (!detail) {
    return (
      <div style={{ padding: 24 }}>
        <p className="tg-body" style={{ color: "var(--tg-text-mute)" }}>
          {error ? `Could not load incident (${error}).` : "Loading incident…"}
        </p>
      </div>
    );
  }

  const inc = detail.incident;
  const stateColor = `var(${THREAT_TOKENS[INCIDENT_THREAT[inc.state] || "calm"]})`;
  const proposed = inc.proposed_tier;
  const inForce = inc.in_force_tier;
  const pending = (detail.enforcement || []).filter(
    (a) => a.requires_confirmation === 1 && ["step_up", "block"].includes(a.tier)
  );
  const confirmedTiers = (detail.enforcement || [])
    .filter((a) => a.requires_confirmation === 0 && a.confirmed_by === "operator")
    .map((a) => a.tier);
  const entityCount = (detail.entities || []).length || 1;

  return (
    <div style={{ padding: 24, maxWidth: 820 }}>
      <h1 className="tg-display-md" style={{ margin: "0 0 4px" }}>
        Incident <span className="tg-mono-data">{inc.incident_id.slice(0, 10)}</span>
      </h1>
      <p className="tg-mono-caption" style={{ color: "var(--tg-text-mute)" }}>
        {inc.state} · proposed <strong>{proposed}</strong> · in force <strong>{inForce}</strong> · policy v{inc.pinned_policy_version}
      </p>

      <Section title="1 · Narrative">
        <NarrativeBlock narrative={inc.narrative} stateColor={stateColor} />
      </Section>

      <Section title="2 · Action bar">
        <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
          {pending.length > 0 ? (
            pending.map((a) => (
              <ConfirmButton
                key={a.action_id}
                tier={a.tier}
                entityCount={entityCount}
                disabled={busy}
                onConfirm={() => act("confirm", { action_id: a.action_id, tier: a.tier })}
              />
            ))
          ) : (
            <button
              className="tg-body-strong"
              disabled
              style={{
                background: "var(--tg-primary-wash)",
                color: "var(--tg-text)",
                border: "1px solid var(--tg-hairline-firm)",
                borderRadius: "var(--tg-radius-sm)",
                padding: "8px 16px",
              }}
            >
              {String(inForce || "monitor").toUpperCase()} in force
            </button>
          )}
          <button
            className="tg-body-strong"
            disabled={busy}
            onClick={() => act("resolve", { resolution: "false_positive" })}
            style={{
              background: "transparent",
              color: "var(--tg-text-2)",
              border: "1px solid var(--tg-hairline-firm)",
              borderRadius: "var(--tg-radius-sm)",
              padding: "8px 16px",
              cursor: busy ? "default" : "pointer",
            }}
          >
            This was legitimate
          </button>
        </div>
        {error && <p className="tg-caption" style={{ color: "var(--tg-attack)" }}>{error}</p>}
      </Section>

      <Section title="3 · Evidence">
        <h3 className="tg-body-strong" style={{ margin: "0 0 6px" }}>Detection timeline</h3>
        <DetectionTimeline timeline={detail.timeline} detector={inc.detector} confirmedTiers={confirmedTiers} />
        <h3 className="tg-body-strong" style={{ margin: "16px 0 6px" }}>Top contributions</h3>
        <ContributionBars contributions={detail.contributions} />
        <h3 className="tg-body-strong" style={{ margin: "16px 0 6px" }}>Entities</h3>
        <EntityTable entities={detail.entities} />
      </Section>

      <Section title="4 · Audit trail">
        <AuditTrail
          timeline={detail.timeline}
          pinnedPolicyVersion={inc.pinned_policy_version}
          resolution={inc.resolution}
          resolvedBy={inc.resolved_by}
        />
      </Section>

      <Section title="5 · Client-asserted evidence">
        <ClientEvidencePanel clientEvidence={detail.client_evidence} />
      </Section>
    </div>
  );
}
