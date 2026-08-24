"""
Source: Day-2 Plan §I acceptance test A12 -- "a hash is a mechanism" (Impl
Plan v2.1 §1.7 / Backend Schema v2 §7). `tests/fixtures/golden.jsonl` etc.
do not exist yet (Day-2 Step 5); this fails with FileNotFoundError until
then. Per Decision 37, this test is characterization-only for *content* --
it never compares golden.jsonl's bytes to a hardcoded expectation, only the
committed hash to a fresh recompute from the committed bytes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
SHA_FILE = FIXTURES_DIR / "golden.sha256"


def _parse_sha256sum_file(path: Path) -> dict:
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, filename = line.partition("  ")
        assert digest and filename, f"malformed sha256sum line: {line!r}"
        entries[filename.strip()] = digest.strip()
    return entries


class TestA12FixtureHashIntegrity:
    def test_golden_sha256_file_exists_and_is_well_formed(self):
        assert SHA_FILE.exists(), f"missing {SHA_FILE}"
        entries = _parse_sha256sum_file(SHA_FILE)
        assert entries, f"{SHA_FILE} contains no entries"
        for filename in entries:
            assert (FIXTURES_DIR / filename).exists(), f"{SHA_FILE} references missing file {filename}"

    def test_every_committed_fixture_hash_matches_a_fresh_recompute(self):
        entries = _parse_sha256sum_file(SHA_FILE)
        for filename, expected_digest in entries.items():
            actual_bytes = (FIXTURES_DIR / filename).read_bytes()
            actual_digest = hashlib.sha256(actual_bytes).hexdigest()
            assert actual_digest == expected_digest, (
                f"{filename}: committed hash {expected_digest} does not match "
                f"a fresh SHA-256 of the committed bytes ({actual_digest}) -- "
                f"the fixture was edited without regenerating golden.sha256"
            )

    def test_golden_jsonl_uses_lf_newlines_only(self):
        # Source: Day-2 Plan §I Step 5 failure modes -- "CRLF on Windows
        # (files must be opened newline='\n')". A CRLF fixture would still
        # hash-match itself but silently break byte-identity across
        # platforms the moment it is regenerated on a different OS.
        golden = FIXTURES_DIR / "golden.jsonl"
        assert golden.exists(), f"missing {golden}"
        raw = golden.read_bytes()
        assert b"\r\n" not in raw, "golden.jsonl contains CRLF line endings"
