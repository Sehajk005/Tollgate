// Day 8, Step 7 -- operator-facing feature names for the contribution bars
// (UIUX v2 SS6.7: "Distinct cards from this IP (5 min)", not
// `distinct_cards_per_ip_5m_q`). One dictionary, beside the feature list.
// Unknown names fall through to the raw identifier.

export const FEATURE_LABELS = {
  attempts_per_ip_60s: "Attempts from this IP (60 s)",
  attempts_per_ip_5m: "Attempts from this IP (5 min)",
  attempts_per_ipua_5m: "Attempts from this IP + device (5 min)",
  attempts_per_session: "Attempts in this session",
  distinct_cards_per_ip_5m: "Distinct cards from this IP (5 min)",
  distinct_cards_per_ip_5m_q: "Distinct cards from this IP (5 min, store quantile)",
  distinct_cards_per_ipua_5m_q: "Distinct cards from this IP + device (store quantile)",
  distinct_cards_per_bin_5m: "Distinct cards against this card range (5 min)",
  distinct_bins_per_ip_5m: "Distinct card ranges from this IP (5 min)",
  distinct_ips_per_bin_5m: "Distinct source IPs against this card range (5 min)",
  bin_hhi_5m: "Card-range concentration (5 min)",
  bin_entropy_5m: "Card-range spread (5 min)",
  bin_is_foreign_issued: "Foreign-issued card range",
  foreign_bin_share_5m: "Foreign card-range share (5 min)",
  card_seen_24h: "Card seen in the last 24 h",
  amount_percentile_vs_store: "Amount vs this store's typical order",
  distinct_amounts_per_ip_5m: "Distinct amounts from this IP (5 min)",
  store_volume_deviation_sigma: "Store volume vs baseline",
  decline_rate_per_ip_5m: "Decline rate from this IP (5 min)",
  invalid_cvv_share_ip_5m: "Invalid-CVV share from this IP (5 min)",
  event_id_reuse_count: "Repeated event id",
  clock_skew_s: "Client clock skew",
};

export function featureLabel(name) {
  return FEATURE_LABELS[name] || name;
}
