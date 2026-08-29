"""
Source: Day-6 Plan §4 -- the Layer 2a analytic gate.

  * steps-to-alarm on a synthetic step matches the closed form
    h / (lam1*ln(lam1/lam0) - (lam1 - lam0))            [TRD §6.5 prop 1]
  * an empty bucket decays S_t by EXACTLY (lam1 - lam0)  [TRD §6.5 prop 4]
  * ARL0 on pure Poisson(lam0) noise at the CONFIGURED h (policy_config.cusum_h,
    tuned by scripts/tune_cusum.py from negative controls only) clears the
    8,640-bucket target (= 24 virtual hours; Day-6 Plan D3).

Every expectation is analytic or a closed form -- no recorded number
(Day-6 Plan §1: "Layer 2 has no independent oracle and never will").
"""

from __future__ import annotations

import json
import math

from packages.detect.cusum import CusumParams, PoissonCusum, poisson_cusum_increment, steps_to_alarm
from packages.storage.db import connect
from scripts.tune_cusum import arl0_on_poisson_noise

TARGET_ARL0_BUCKETS = 8640  # Source: config/policy.yaml cusum.target_arl0_buckets / Day-6 Plan D3


def _increment_real(n_real: float, lam0: float, rho: float) -> float:
    lam1 = rho * lam0
    return n_real * math.log(lam1 / lam0) - (lam1 - lam0)


class TestCusumAnalytic:
    def test_steps_to_alarm_closed_form_matches_the_recursion(self):
        # Source: TRD §6.5 prop 1. Drive the recursion with n_t exactly equal
        # to lam1 (the sustained attack rate) so the per-bucket drift is
        # lam1*ln(lam1/lam0) - (lam1 - lam0) -- the closed form's denominator.
        for lam0, rho, h in [(2.0, 5.0, 40.0), (1.0, 4.0, 25.0), (0.5, 6.0, 60.0)]:
            lam1 = rho * lam0
            predicted = steps_to_alarm(h, lam0, lam1)
            s = 0.0
            steps = 0
            while s <= h and steps < 100_000:
                s = max(0.0, s + _increment_real(lam1, lam0, rho))
                steps += 1
            assert math.isclose(steps, math.ceil(predicted), abs_tol=1.0), (
                f"lam0={lam0} rho={rho} h={h}: recursion {steps} vs closed form {predicted}"
            )

    def test_empty_bucket_decays_S_by_exactly_lam1_minus_lam0(self):
        # Source: TRD §6.5 prop 4.
        lam0, rho = 3.0, 5.0
        lam1 = rho * lam0
        params = CusumParams(rho=rho, h=1000.0, bucket_s=10, lambda_min=0.01)
        cusum = PoissonCusum(params)
        for b in range(6):
            cusum.observe(b, 30, lam0)
        s_before = cusum.s
        step = cusum.observe(6, 0, lam0)
        assert math.isclose(s_before - step.s, lam1 - lam0, rel_tol=1e-12)
        assert math.isclose(poisson_cusum_increment(0, lam0, lam1), -(lam1 - lam0), rel_tol=1e-12)

    def test_arl0_on_pure_noise_at_the_configured_h_clears_the_target(self, day5_corpus):
        # Read the tuned policy_config + learned baseline for a merchant the
        # tuner actually tuned against (a negative-control merchant).
        merchant = "m-eval-12"
        conn = connect(day5_corpus)
        try:
            row = conn.execute(
                "SELECT cusum_h, cusum_rho, cusum_bucket_s FROM policy_config "
                "WHERE merchant_id = ? ORDER BY version DESC LIMIT 1",
                (merchant,),
            ).fetchone()
            base = conn.execute(
                "SELECT hourly_volume_profile, flagged_rate_mean FROM store_baseline "
                "WHERE merchant_id = ?",
                (merchant,),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None and row["cusum_h"] > 5.0, (
            "policy_config still carries the placeholder cusum_h=5.0 -- run scripts.tune_cusum"
        )
        assert base is not None, "store_baseline missing -- run scripts.learn_store_baseline"
        h = float(row["cusum_h"])
        rho = float(row["cusum_rho"])
        bucket_s = int(row["cusum_bucket_s"])
        hv = json.loads(base["hourly_volume_profile"])
        p_bar_0 = float(base["flagged_rate_mean"])
        lam0_bar = (sum(hv) / len(hv)) / 3600.0 * bucket_s * p_bar_0

        arl0 = arl0_on_poisson_noise(
            h, lam0_bar, rho, 0.01, bucket_s, seed=12345, n_buckets=TARGET_ARL0_BUCKETS * 2
        )
        assert arl0 >= TARGET_ARL0_BUCKETS, (
            f"ARL0 on Poisson({lam0_bar:.4f}) noise at h={h:.2f} is {arl0:.0f} < {TARGET_ARL0_BUCKETS}"
        )

    def test_arl0_grows_monotonically_with_h(self):
        lam0 = 0.5
        arls = [
            arl0_on_poisson_noise(h, lam0, 5.0, 0.01, 10, seed=7, n_buckets=6000)
            for h in (2.0, 6.0, 12.0)
        ]
        assert arls[0] <= arls[1] <= arls[2]
