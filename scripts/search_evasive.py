r"""
python -m scripts.search_evasive --seed 42 --budget 200 --patience 40 \
    --demo-db tollgate.db --model-dir models/ \
    --write-config config/attack_tiers.yaml --trace eval/outputs/evade_search.json

python -m scripts.search_evasive --append-corpus --seed 42 --db data/corpus/tollgate.db

Source: Day-7 Plan §4 Step 7 / §6 / §7 -- the OFFLINE driver for Tier E. It
owns the frozen detector and supplies `evaluate_fn`; the pure search lives in
`packages/simulator/evade.py`. Mirrors the established shape of
`scripts/train_l1.py` / `scripts/tune_cusum.py` / `scripts/learn_store_baseline.py`.

The detector is built EXACTLY as `eval/corpus.py::_replay_one` builds it --
`InMemoryWindowStore`, `DayOneRules`, `InProcessEventBus`, driven through
`ReplayDriver.run(request, stream=...)` -- plus the frozen `models/` bundle
(`ScorerState._load_model`) and the frozen policy/baseline
(`ScorerState._load_layer2`). `score_calibrated` and `incident` are read back
from the spool payload via a local recording spool; zero production change,
the scoring core is the identical one `/v1/score` runs.

Runs entirely offline: no socket, no subprocess, no scorer import from the
simulator package. `theta_challenge` is DERIVED from the pinned policy_config,
never a literal (Decision 70).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import tempfile
from pathlib import Path

from packages.simulator.evade import EpisodeOutcome, SearchSpace, render_evasive_yaml_text, search

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_DIR = REPO_ROOT / "models"
DEFAULT_DEMO_DB = REPO_ROOT / "tollgate.db"
DEFAULT_CORPUS_DB = REPO_ROOT / "data" / "corpus" / "tollgate.db"
DEFAULT_TRACE = REPO_ROOT / "eval" / "outputs" / "evade_search.json"


def _theta_challenge(demo_db: Path) -> float:
    """Derived from the pinned policy_config's tier ladder -- never a literal."""
    from packages.storage.db import connect
    from packages.storage.repository import load_policy_config
    from services.scorer.deps import DEMO_MERCHANT_ID

    conn = connect(demo_db, read_only=True)
    try:
        snap = load_policy_config(conn, DEMO_MERCHANT_ID)
    finally:
        conn.close()
    if snap is None or "challenge" not in (snap.thresholds or {}):
        raise SystemExit(
            f"{demo_db} has no policy_config with a populated `challenge` threshold; "
            "seed it (scripts.seed_merchant + scripts.learn_store_baseline + scripts.tune_cusum) first"
        )
    return float(snap.thresholds["challenge"])


class _RecordingSpool:
    """Duck-types Spool.append/close; keeps every payload in memory."""

    def __init__(self, scratch: Path) -> None:
        self.path = scratch
        self.rows: list = []

    def append(self, key: str, payload: dict) -> None:
        self.rows.append(payload)

    def close(self) -> None:
        pass


def _make_evaluate_fn(*, seed: int, model_dir: Path, demo_db: Path):
    from packages.clock.clock import SystemClock
    from packages.clock.ids import UlidGenerator
    from packages.detect.rules import DayOneRules
    from packages.features.memory_store import InMemoryWindowStore
    from packages.simulator.generate import build_stream
    from packages.storage.bus import InProcessEventBus
    from packages.storage.drainer import Drainer
    from services.scorer.deps import DEMO_MERCHANT_ID, ScorerState
    from services.scorer.replay import ReplayDriver, ReplayRequest

    # The model is stateless -> load once. Layer 2 (Layer2Engine /
    # IncidentRegistry) is stateful -> reload per candidate so no CUSUM / drift
    # / incident state leaks between evaluations.
    model, calibrator = ScorerState._load_model(model_dir)
    scratch = Path(tempfile.mkdtemp(prefix="evade_"))

    def evaluate(params: dict) -> EpisodeOutcome:
        tier_cfg = {
            "attempts_per_hour": {"value": int(params["attempts_per_hour"])},
            "ip_pool_size": {"value": int(params["ip_pool_size"])},
            "distinct_cards": {"value": int(params["distinct_cards"])},
            "bin_pool_size": {"value": int(params["bin_pool_size"])},
            "amount_quantile_band": {
                "min": int(params["amount_quantile_band"]["min"]),
                "max": int(params["amount_quantile_band"]["max"]),
            },
            "episode_duration_s": {"value": int(params["episode_duration_s"])},
        }
        output = build_stream(
            seed=seed, tier="evasive", hours=3, attack_tiers={"evasive": tier_cfg}
        )

        policy, baseline, layer2, incidents, engine, ttl_ms = ScorerState._load_layer2(
            demo_db, DEMO_MERCHANT_ID
        )

        window_store = InMemoryWindowStore()
        clock = SystemClock()  # unused for timing -- the driver installs a VirtualClock
        spool = _RecordingSpool(scratch)
        state = ScorerState(
            clock=clock,
            ulid=UlidGenerator(clock=clock, rng=random.Random(f"evade:ulid:{seed}")),
            window_store=window_store,
            rules=DayOneRules(window_store),
            spool=spool,
            drainer=Drainer(db_path=demo_db, spool_path=scratch / "unused.spool"),
            event_bus=InProcessEventBus(),
            db_path=demo_db,
            model=model,
            calibrator=calibrator,
            policy=policy,
            baseline=baseline,
            layer2=layer2,
            incidents=incidents,
            policy_engine=engine,
            enforcement_ttl_ms=ttl_ms,
            policy_versions={policy.version: policy} if policy is not None else {},
        )

        driver = ReplayDriver(state, merchant_id=DEMO_MERCHANT_ID)
        asyncio.run(driver.run(
            ReplayRequest(tier="evasive", seed=seed, speed=0, epoch_ms=0),
            stream=list(output.events),
        ))

        attack_event_ids = {lbl.event_id for lbl in output.labels if lbl.is_attack}
        card_by_event = {e.event_id: e.card_hash for e in output.events}
        authorized_cards = {
            card_by_event[lbl.event_id]
            for lbl in output.labels
            if lbl.is_attack and lbl.gateway_status == "authorized"
        }
        duration_s = max(int(params["episode_duration_s"]), 1)
        cards_validated_per_hour = len(authorized_cards) / (duration_s / 3600.0)

        scores: list = []
        incident_opened = False
        cards_exposed_before_alert = None
        for payload in spool.rows:
            attempt = payload.get("attempt", {})
            score = payload.get("score", {})
            if attempt.get("event_id") in attack_event_ids:
                scores.append(float(score.get("score_calibrated", 0.0)))
            if "incident" in payload:
                incident_opened = True
                inc = payload["incident"]
                if cards_exposed_before_alert is None:
                    cards_exposed_before_alert = inc.get("cards_exposed_before_alert")

        return EpisodeOutcome(
            mean_score_calibrated=(sum(scores) / len(scores)) if scores else 0.0,
            incident_opened=incident_opened,
            cards_validated_per_hour=cards_validated_per_hour,
            attempts_total=len(attack_event_ids),
            cards_exposed_before_alert=cards_exposed_before_alert,
        )

    return evaluate


def _run_search(args: argparse.Namespace) -> None:
    theta = _theta_challenge(Path(args.demo_db))
    evaluate_fn = _make_evaluate_fn(
        seed=args.seed, model_dir=Path(args.model_dir), demo_db=Path(args.demo_db)
    )
    result = search(
        seed=args.seed,
        budget=args.budget,
        patience=args.patience,
        theta_challenge=theta,
        evaluate_fn=evaluate_fn,
        space=SearchSpace(),
    )

    trace_path = Path(args.trace)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(json.dumps({
        "seed": args.seed,
        "budget": args.budget,
        "patience": args.patience,
        "theta_challenge": result.theta_challenge,
        "converged": result.converged,
        "stopped_reason": result.stopped_reason,
        "n_evaluated": result.n_evaluated,
        "best_objective_cards_validated_per_hour": (
            None if result.best_objective == float("-inf") else result.best_objective
        ),
        "best_params": result.best_params,
        "trace": result.trace,
    }, indent=2), encoding="utf-8")
    print(f"wrote {trace_path} ({result.n_evaluated} candidates, stopped: {result.stopped_reason})")

    if not result.converged:
        print(
            "Tier-E search did NOT converge -- no feasible candidate under "
            f"theta_challenge={result.theta_challenge:.6f} without opening an incident. "
            "config/attack_tiers.yaml is left untouched (the cut rule applies)."
        )
        return

    print(
        f"Tier-E converged: cards_validated_per_hour={result.best_objective:.4f} "
        f"at {result.best_params}"
    )

    if args.write_config:
        cfg_path = Path(args.write_config)
        text = cfg_path.read_text(encoding="utf-8")
        head, sep, _tail = text.partition("\nevasive:")
        if not sep:
            raise SystemExit(f"{cfg_path} has no `evasive:` block to replace")
        block = render_evasive_yaml_text(result.best_params, seed=args.seed, budget=args.budget)
        cfg_path.write_text(head.rstrip("\n") + "\n\n" + block, encoding="utf-8")
        print(f"rewrote the `evasive:` block in {cfg_path}")


def _append_corpus(args: argparse.Namespace) -> None:
    from eval.corpus import build_tier_e_runs, replay_corpus

    db_path = Path(args.db)
    spool_dir = db_path.parent / "spool"
    runs = build_tier_e_runs(args.seed)
    result = replay_corpus(runs, db_path=db_path, spool_dir=spool_dir, rebuild=False)
    print(
        f"appended {result.n_runs} Tier-E run(s) to {db_path}: "
        f"{result.n_attempts} attempts, {result.n_episodes_written} episode row(s)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--budget", type=int, default=200)
    parser.add_argument("--patience", type=int, default=40)
    parser.add_argument("--demo-db", dest="demo_db", type=Path, default=DEFAULT_DEMO_DB)
    parser.add_argument("--db", dest="db", type=Path, default=DEFAULT_CORPUS_DB)
    parser.add_argument("--model-dir", dest="model_dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--write-config", dest="write_config", type=Path, default=None)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--append-corpus", dest="append_corpus", action="store_true")
    args = parser.parse_args()

    if args.append_corpus:
        _append_corpus(args)
    else:
        _run_search(args)


if __name__ == "__main__":
    sys.exit(main())
