"""
Source: remediation plan §20 -- source-contract tests for the frontend fixes,
in the established `test_ui_threat_band.py` / `test_simulator_safety.py` idiom.
No JS test runner is added (Day-8 Risk R7's standing decision).

These scan source. A source scan CANNOT prove rendering, which is exactly why
§23's browser pass is a separate, mandatory gate -- these tests exist to stop a
fix being silently reverted, not to substitute for looking at the screen.

Covers AUDIT-008, 009, 011, 012, 013, 014, 015, 016, 017, 018, 020, 022, 023, 024.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DASH = REPO_ROOT / "services" / "dashboard"
STORE = REPO_ROOT / "services" / "storefront"
DASH_SRC = DASH / "src"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def code(path: Path) -> str:
    """Source with comments stripped.

    Every "this must NOT appear" assertion runs against this rather than the raw
    text: these files DOCUMENT the defect they fixed, quoting the old code
    verbatim, and a contract test that cannot tell an explanation from an
    implementation would force the explanation to be deleted. Handles `//` line
    comments, `/* */` blocks and JSX `{/* */}` comments; string literals in this
    codebase never contain `//`, and the assertions below are all on code
    shapes, not on URLs."""
    src = read(path)
    src = re.sub(r"\{/\*.*?\*/\}", "", src, flags=re.DOTALL)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"^[ 	]*//.*$", "", src, flags=re.MULTILINE)
    return src


class TestReplayStatusIsAuthoritative:
    """FIX-012 / AUDIT-002, 003, 013."""

    def test_the_hook_polls_the_status_endpoint(self):
        src = read(DASH_SRC / "hooks" / "useReplayStatus.js")
        assert "/v1/replay/status" in src, "the hook never asks the backend"
        assert "setTimeout" in src or "setInterval" in src, "there is no poll at all"

    def test_polling_stops_once_the_run_is_terminal(self):
        src = read(DASH_SRC / "hooks" / "useReplayStatus.js")
        assert "isTerminal" in src
        assert re.search(r"if\s*\(\s*isTerminal\([^)]*\)\s*\)\s*return", src), (
            "the poll has no terminal stop condition -- it would burn a request "
            "per second for the life of the tab"
        )

    def test_the_terminal_set_matches_the_backend(self):
        src = read(DASH_SRC / "hooks" / "useReplayStatus.js")
        for state in ("idle", "stopped", "finished", "failed"):
            assert f'"{state}"' in src, f"{state!r} missing from the terminal set"

    def test_an_older_snapshot_is_ignored(self):
        src = read(DASH_SRC / "hooks" / "useReplayStatus.js")
        assert "updated_at_ms" in src, (
            "the reducer cannot order snapshots, so a late control frame could "
            "move the UI backwards"
        )

    def test_app_does_not_derive_replay_state_from_the_event_buffer(self):
        # Remediation FIX-M-031: the live subscriptions moved from App.jsx into
        # components/LiveShell.jsx (mounted only for live/incident). The
        # invariant is unchanged -- replay state comes from useReplayStatus,
        # never from the newest attempt event.
        src = code(DASH_SRC / "components" / "LiveShell.jsx")
        assert "useReplayStatus" in src
        assert "latest?.replay" not in src and "latest.replay" not in src, (
            "LiveShell still reads the replay snapshot off the newest attempt "
            "event -- which is exactly why a finished run rendered as RUNNING forever"
        )

    def test_the_control_strip_derives_disabled_from_the_terminal_set(self):
        src = read(DASH_SRC / "components" / "DemoControlStrip.jsx")
        assert "isTerminal" in src, "the strip guesses at busy-ness instead of asking"
        assert "disabled={disabled}" in src

    def test_the_tier_selector_reconciles_with_the_backend(self):
        src = read(DASH_SRC / "components" / "DemoControlStrip.jsx")
        assert "replayStatus.tier" in src, (
            "the tier selector is never reconciled with the tier the backend is "
            "actually replaying (AUDIT-013)"
        )


class TestBackfillAndRunScopedReset:
    """FIX-013 / FIX-014 -- AUDIT-009, AUDIT-015."""

    def test_the_mount_path_back_fills_outside_the_error_path(self):
        src = read(DASH_SRC / "hooks" / "useEventStream.js")
        assert "/v1/stream/recent" in src
        # The back-fill must be reachable from mount, not only from startPolling.
        mount_region = src.split("openStream();", 1)[-1]
        assert "fetchRecent()" in mount_region, (
            "the back-fill is still only reachable from the SSE error path, so a "
            "dashboard opened mid-attack shows an all-clear screen (AUDIT-009)"
        )

    def test_live_frames_are_queued_until_the_backfill_resolves(self):
        src = read(DASH_SRC / "hooks" / "useEventStream.js")
        assert "backfillPending" in src and "queued" in src, (
            "without a queue the seam either drops events (open after fetch) or "
            "duplicates them (fetch after open)"
        )

    def test_events_are_deduplicated_by_attempt_uid(self):
        src = read(DASH_SRC / "hooks" / "useEventStream.js")
        assert "seenRef" in src or "new Set()" in src
        assert "attempt_uid" in src

    def test_the_effect_is_keyed_on_run_id_and_clears_every_derived_value(self):
        src = read(DASH_SRC / "hooks" / "useEventStream.js")
        assert re.search(r"\}, \[runId\]\);", src), (
            "the stream effect does not depend on runId, so nothing clears when "
            "a run boundary is crossed (AUDIT-015)"
        )
        tail = src.split("useEffect(", 1)[-1]
        for cleared in ("setEvents([])", "lastUidRef.current = null", "setLastEventAt(null)"):
            assert cleared in tail, f"{cleared} is not part of the run-boundary reset"

    def test_control_frames_are_routed_away_from_the_attempt_array(self):
        src = read(DASH_SRC / "hooks" / "useEventStream.js")
        assert "replay_status" in src, (
            "lifecycle control frames would be rendered as attempts"
        )

    def test_the_initial_connection_mode_is_connecting_not_reconnecting(self):
        src = read(DASH_SRC / "hooks" / "useEventStream.js")
        assert 'useState("connecting")' in src, (
            "the chip still opens on 'reconnecting', which reads as degradation "
            "on a perfectly healthy idle system (AUDIT-020)"
        )


class TestIncidentsComeFromTheApi:
    """FIX-015 / AUDIT-008."""

    def test_the_hook_fetches_the_incidents_endpoint(self):
        src = read(DASH_SRC / "hooks" / "useIncidents.js")
        assert "/v1/incidents" in src

    def test_the_sse_buffer_is_not_the_sole_source(self):
        # Remediation FIX-M-031: useIncidents moved to components/LiveShell.jsx.
        src = code(DASH_SRC / "components" / "LiveShell.jsx")
        assert "useIncidents" in src
        assert "inc.state !== \"CLOSED\"" not in src, (
            "LiveShell still picks the incident by scanning the 200-event SSE "
            "buffer, so D3 becomes unreachable once the opening event rotates out"
        )

    def test_the_dead_sse_incident_prop_is_gone(self):
        """Plan F-H: App passed `sseIncident`, D3Incident never destructured it."""
        assert "sseIncident" not in code(DASH_SRC / "App.jsx")
        assert "sseIncident" not in code(DASH_SRC / "screens" / "D3Incident.jsx")

    def test_loading_empty_and_error_are_distinct_states(self):
        src = read(DASH_SRC / "screens" / "D3Incident.jsx")
        assert "listError" in src and "listLoading" in src, (
            "a failed fetch would render as 'No incidents', which tells the "
            "operator the opposite of the truth"
        )

    def test_incidents_are_refetched_on_a_run_boundary(self):
        src = read(DASH_SRC / "hooks" / "useIncidents.js")
        assert "runId" in src

    def test_the_sse_trigger_is_debounced_not_polled(self):
        src = read(DASH_SRC / "hooks" / "useIncidents.js")
        assert "DEBOUNCE_MS" in src
        assert "setInterval" not in src, "incidents are polled on a timer"


class TestAttemptsTileTruthfulness:
    """FIX-016 / AUDIT-017."""

    def test_the_tile_reads_the_server_window(self):
        src = read(DASH_SRC / "screens" / "D1Live.jsx")
        assert "attempts_per_merchant_5m" in src, (
            "the tile still counts the capped frontend buffer"
        )

    def test_the_tile_no_longer_counts_the_event_array(self):
        src = code(DASH_SRC / "screens" / "D1Live.jsx")
        assert "FIVE_MIN_MS" not in src, (
            "the event-buffer filter is still present; the tile can silently cap "
            "at 200 during the burst it exists to show"
        )


class TestStreamRailSizing:
    """FIX-017 / AUDIT-016."""

    def test_a_resize_observer_repaints_the_rail(self):
        src = read(DASH_SRC / "components" / "StreamRail.jsx")
        assert "ResizeObserver" in src, (
            "canvas.width is still set once at first paint, so a resize stretches "
            "the bitmap instead of repainting it"
        )

    def test_the_backing_store_is_dpr_aware(self):
        src = read(DASH_SRC / "components" / "StreamRail.jsx")
        assert "devicePixelRatio" in src
        assert "setTransform" in src or "ctx.scale" in src

    def test_the_pitch_is_derived_from_the_width(self):
        src = read(DASH_SRC / "components" / "StreamRail.jsx")
        assert "tickPitch" in src
        assert "width / count" in src, (
            "the pitch is still a fixed constant, so the buffer can only ever "
            "cover 800 px however wide the viewport is"
        )

    def test_the_buffer_spans_the_canvas_at_a_wide_viewport(self):
        """The arithmetic the audit measured: 200 events x 4 px = 800 px max."""
        src = read(DASH_SRC / "components" / "StreamRail.jsx")
        m = re.search(r"const MIN_PITCH = (\d+);", src)
        assert m, "MIN_PITCH not found"
        min_pitch = int(m.group(1))
        # At 1536 px with a full 200-event buffer the derived pitch must exceed
        # the floor -- i.e. the rail fills rather than stopping at 800 px.
        assert 1536 / 200 > min_pitch is not None
        assert 1536 / 200 >= min_pitch, "the derived pitch would collapse to the floor"


class TestThreatBandWash:
    """FIX-018 / AUDIT-018."""

    def test_no_var_string_concatenation_remains(self):
        src = code(DASH_SRC / "components" / "ThreatBand.jsx")
        assert "})1A`" not in src and ")1A" not in src, (
            "the wash is still built by concatenating an alpha suffix onto a "
            "var() call, which produces an invalid colour the browser drops"
        )

    def test_every_state_maps_to_a_token_defined_in_tokens_css(self):
        labels = read(DASH_SRC / "lib" / "labels.js")
        tokens_css = read(DASH_SRC / "styles" / "tokens.css")
        m = re.search(r"THREAT_WASH_TOKENS\s*=\s*\{(.*?)\}", labels, re.DOTALL)
        assert m, "THREAT_WASH_TOKENS is not defined"
        mapping = dict(re.findall(r'(\w+)\s*:\s*"([^"]+)"', m.group(1)))
        for state in ("calm", "elevated", "under_attack", "resolved"):
            assert state in mapping, f"no wash token for {state!r}"
            assert f"{mapping[state]}:" in tokens_css, (
                f"{mapping[state]} is not defined in tokens.css"
            )

    def test_the_band_uses_the_map(self):
        src = read(DASH_SRC / "components" / "ThreatBand.jsx")
        assert "THREAT_WASH_TOKENS" in src


# TestD6Resolvability (FIX-019 / AUDIT-011) was removed per
# METRICS-REMEDIATION-PLAN-2026-09-02.md §26.2: it grep-scanned D6Metrics.jsx /
# BarRow.jsx (the superseded shared-bar primitive) for the strings that proved an
# unresolvable metric never reaches `.toFixed()`. That invariant is now enforced
# by real rendering tests: services/dashboard/src/components/metrics/
# UnavailableGroup.test.jsx, .../Block1PerTier.test.jsx (FE-T-B1 "no recall
# renders as a number"; 1c renders `ap_raw` as the resolvable alternative), and
# src/lib/d6Contract.test.js (FE-T-CONTRACT: every missing-value case ->
# available === false, never a number).


class TestTickerHasNoBlankColumn:
    """FIX-020 / AUDIT-023."""

    def test_the_grid_has_no_column_that_renders_nothing(self):
        src = code(DASH_SRC / "components" / "EventTicker.jsx")
        assert '<span>{unscored ? "—" : ""}</span>' not in src, (
            "the permanently blank score column is still rendered"
        )

    def test_unscored_rows_still_read_as_unscored(self):
        """SS6.4's actual requirement, which must survive removing the column."""
        src = read(DASH_SRC / "components" / "EventTicker.jsx")
        assert "unscored" in src
        assert "—" in src


class TestStorefrontFieldsAreReal:
    """FIX-021 / AUDIT-019."""

    def test_the_card_hash_is_derived_not_random(self):
        src = code(STORE / "src" / "screens" / "S2Checkout.jsx")
        assert "crypto.subtle.digest" in src, (
            "card_hash is still random, so every attempt looks like a brand-new "
            "card and card testing cannot be demonstrated at all"
        )
        assert 'card_hash: `card-${Math.random()' not in src

    def test_the_bin_is_derived_from_the_typed_number(self):
        src = code(STORE / "src" / "screens" / "S2Checkout.jsx")
        assert 'bin: "999001"' not in src, "the BIN is still hardcoded"
        assert "digits.slice(0, 6)" in src

    def test_the_pan_never_appears_in_the_request_body(self):
        """The trust boundary: only BIN, last4, expiry and an opaque digest."""
        src = read(STORE / "src" / "screens" / "S2Checkout.jsx")
        body = src.split("body: JSON.stringify(", 1)[1].split("})", 1)[0]
        for banned in ("pan", "digits,", "cardNumber", "cvv"):
            assert banned not in body, f"{banned!r} is in the /v1/score request body"
        assert "card_hash: cardHash" in body
        assert "last4: digits.slice(-4)" in body

    def test_the_inputs_are_controlled(self):
        src = code(STORE / "src" / "screens" / "S2Checkout.jsx")
        assert "defaultValue" not in src, (
            "the inputs are still uncontrolled, so nothing reads what is typed"
        )
        assert "value={pan}" in src and "onChange={(e) => setPan" in src

    def test_malformed_input_is_rejected_not_silently_substituted(self):
        src = read(STORE / "src" / "screens" / "S2Checkout.jsx")
        assert "validateCard" in src and "validationError" in src


class TestControlsAndCopy:
    """FIX-022 / FIX-023 -- AUDIT-024, AUDIT-022."""

    def test_neither_shell_still_says_day_1(self):
        for path in (DASH / "index.html", STORE / "index.html"):
            assert "(Day 1)" not in read(path), f"{path} still carries a Day-1 title"

    def test_the_titles_are_the_approved_ones(self):
        assert "Tollgate &mdash; Live Monitor" in read(DASH / "index.html")
        assert "Kesar &amp; Co. &mdash; Checkout" in read(STORE / "index.html")

    def test_stop_reset_and_both_selects_are_styled(self):
        src = read(DASH_SRC / "components" / "DemoControlStrip.jsx")
        assert "selectStyle" in src, "the <select>s are raw browser defaults"
        assert "buttonStyle" in src, "Stop and Reset are raw browser defaults"
        assert src.count("style={selectStyle}") >= 2

    def test_the_stale_evasive_disabled_comment_is_gone(self):
        src = read(DASH_SRC / "components" / "DemoControlStrip.jsx")  # comments INCLUDED: that is the point
        assert "`evasive` disabled" not in src, (
            "the header comment still says evasive is disabled while "
            "TIER_OPTIONS enables it"
        )
        assert "enabled: false" not in src

    def test_errors_never_stringify_a_null_body(self):
        src = code(DASH_SRC / "components" / "DemoControlStrip.jsx")
        assert "JSON.stringify(data)" not in src, (
            "an unparsed body still renders as the literal HTTP 500: NULL"
        )
        assert "data.detail" in src, "the server's own explanation is not used"

    def test_the_required_error_copy_is_present(self):
        src = read(DASH_SRC / "components" / "DemoControlStrip.jsx")
        assert "API key rejected" in src and "VITE_TOLLGATE_API_KEY" in src
        assert "A replay is already running" in src
        assert "Scorer unavailable" in src
        assert "Cannot reach the scorer" in src

    def test_errors_clear_on_success_and_after_a_timeout(self):
        src = read(DASH_SRC / "components" / "DemoControlStrip.jsx")
        assert "ERROR_CLEAR_MS" in src
        assert "setActionError(null)" in src

    def test_a_degraded_reset_is_surfaced(self):
        src = read(DASH_SRC / "components" / "DemoControlStrip.jsx")
        assert "degraded" in src and "cleared" in src, (
            "a partially-failed reset would report plain success"
        )


class TestPaceFromControl:
    """FIX-011 / AUDIT-014."""

    def test_the_strip_offers_the_pacing_control(self):
        src = read(DASH_SRC / "components" / "DemoControlStrip.jsx")
        assert "pace_from" in src
        assert 'type="checkbox"' in src


class TestNoStaleDayOneComments:
    def test_no_source_file_claims_a_behaviour_the_code_no_longer_has(self):
        """A targeted sweep, not a blanket ban on the word 'Day': the Day-N
        provenance comments are deliberate and stay. These are the specific
        claims the remediation made false."""
        stale = {
            "`evasive` disabled": DASH_SRC / "components" / "DemoControlStrip.jsx",
            "(Day 1)": DASH / "index.html",
        }
        for phrase, path in stale.items():
            assert phrase not in read(path), f"{path.name} still says {phrase!r}"
