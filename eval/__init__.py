"""
Source: Day-4 Plan (rev. 2) §2 discrepancy 1 -- eval/ lives at repo root
(TRD §3, Schema §9 step 7), not inside packages/simulator (Decision 28
settled the simulator half of this fork). pyproject.toml's
[tool.setuptools.packages.find] include gains "eval*" so this package is
discoverable the same way packages*/services*/scripts* already are.
"""

from __future__ import annotations
