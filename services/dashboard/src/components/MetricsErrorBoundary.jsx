// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §19.3 / FIX-M-019 / RC-3.
//
// A class error boundary wrapping ONLY the Metrics route content, so a bad
// artifact degrades one screen and never the shell (App.jsx keeps the nav,
// Stream Rail and threat band mounted). The fallback is actionable, not an
// apology (UIUX §8: "Errors say what happened and what to do. They don't
// apologise").
//
//   * `d6Contract.parseArtifact` throws a typed `ArtifactContractError` whose
//     message already carries the regeneration command -- rendered verbatim.
//   * DEV additionally renders the stack and the offending `path`.
//   * `componentDidCatch` ALWAYS `console.error`s the original -- the boundary
//     never swallows a real error ("Do not hide real errors" is satisfied by
//     always logging and always naming the cause).

import { Component } from "react";

const REGEN =
  "python -m eval.harness --split all --seed 42 " +
  "--corpus-db data/corpus/tollgate.db --model-dir models";

export default class MetricsErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    // ALWAYS surface the original -- the boundary is a graceful *degradation*,
    // not a silencer. Anyone with a console still sees the true failure.
    // eslint-disable-next-line no-console
    console.error("MetricsErrorBoundary caught an error rendering the Metrics route:", error, info);
  }

  render() {
    const { error, info } = this.state;
    if (error == null) return this.props.children;

    const isDev = Boolean(import.meta.env && import.meta.env.DEV);
    const named = error && typeof error.message === "string" && error.message.length > 0;
    const path = error && error.path ? String(error.path) : null;

    return (
      <div
        role="alert"
        className="tg-body"
        style={{ padding: 24, maxWidth: 760, color: "var(--tg-text)" }}
      >
        <h2 className="tg-display-sm" style={{ margin: "0 0 8px" }}>
          The evaluation artifact could not be read.
        </h2>
        <p className="tg-body" style={{ color: "var(--tg-text-2)", margin: "0 0 12px" }}>
          {named
            ? error.message
            : "eval/outputs/d6.json could not be parsed by this build."}
        </p>
        {path && (
          <p className="tg-mono-caption" style={{ color: "var(--tg-text-2)", margin: "0 0 12px" }}>
            offending path: <code>{path}</code>
          </p>
        )}
        <p className="tg-body" style={{ color: "var(--tg-text-2)", margin: "0 0 6px" }}>
          Regenerate it with:
        </p>
        <pre
          className="tg-mono-data"
          style={{
            margin: 0,
            padding: "10px 12px",
            background: "var(--tg-surface-2)",
            borderRadius: 6,
            overflowX: "auto",
            color: "var(--tg-text)",
          }}
        >
          {REGEN}
        </pre>
        {isDev && error && error.stack && (
          <pre
            className="tg-mono-caption"
            style={{
              marginTop: 12,
              padding: "10px 12px",
              background: "var(--tg-surface-1)",
              borderRadius: 6,
              overflowX: "auto",
              color: "var(--tg-text-mute)",
              whiteSpace: "pre-wrap",
            }}
          >
            {error.stack}
            {info && info.componentStack ? `\n${info.componentStack}` : ""}
          </pre>
        )}
      </div>
    );
  }
}
