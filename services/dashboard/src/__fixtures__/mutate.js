// Source: METRICS-REMEDIATION-PLAN-2026-09-02.md §18.5 / §23.5 -- pure helpers
// for deriving fixtures from the REAL artifact in memory. No fixture is ever
// created by editing eval/outputs/d6.json.

/** structuredClone if available, else a JSON round-trip (artifacts are pure JSON). */
export function deepClone(obj) {
  if (typeof structuredClone === "function") return structuredClone(obj);
  return JSON.parse(JSON.stringify(obj));
}

const parts = (path) => (Array.isArray(path) ? path : String(path).split("."));

/** Return a clone of `obj` with the leaf at `path` deleted. */
export function deepDelete(obj, path) {
  const out = deepClone(obj);
  const keys = parts(path);
  let node = out;
  for (let i = 0; i < keys.length - 1; i += 1) {
    if (node == null || typeof node !== "object") return out;
    node = node[keys[i]];
  }
  if (node && typeof node === "object") delete node[keys[keys.length - 1]];
  return out;
}

/** Return a clone of `obj` with the leaf at `path` set to `value`. */
export function deepSet(obj, path, value) {
  const out = deepClone(obj);
  const keys = parts(path);
  let node = out;
  for (let i = 0; i < keys.length - 1; i += 1) {
    if (node[keys[i]] == null || typeof node[keys[i]] !== "object") node[keys[i]] = {};
    node = node[keys[i]];
  }
  node[keys[keys.length - 1]] = value;
  return out;
}

/** Enumerate every scalar leaf of `obj` as a dotted path (list items -> `foo.3`). */
export function leafPaths(obj, prefix = "", out = []) {
  if (obj !== null && typeof obj === "object") {
    const entries = Array.isArray(obj)
      ? obj.map((v, i) => [String(i), v])
      : Object.entries(obj);
    if (entries.length === 0) out.push(prefix || "<root>");
    for (const [k, v] of entries) {
      leafPaths(v, prefix ? `${prefix}.${k}` : k, out);
    }
  } else {
    out.push(prefix || "<root>");
  }
  return out;
}
