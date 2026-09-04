// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §23.5 -- the committed artifact,
// UNMODIFIED. Tests that assert the page shows the truth run against the truth
// (`₹2,32,145`, `0.789`, `0.731`, `0.9998` are all asserted against this file).
//
// This is the same build-time `import` path the app uses, resolved through
// Vitest's inherited `server.fs.allow` (see vitest.config.js).
import realArtifact from "../../../../eval/outputs/d6.json";

export default realArtifact;
