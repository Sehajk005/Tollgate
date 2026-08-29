"""
Source: Day-4 Plan (rev. 2) §6 test 13 -- "config_hash / build_hash."
Moving a line between two config files CHANGES the hash; adding a comment
does NOT; changing HEAD changes build_hash but not config_hash (F16).
"""

from __future__ import annotations

from eval.provenance import build_hash, config_hash


class TestConfigHash:
    def test_moving_a_leaf_between_two_config_files_changes_the_hash(self, tmp_path):
        # Build two small config files, then move one leaf from A to B.
        a_path = tmp_path / "a.yaml"
        b_path = tmp_path / "b.yaml"
        a_path.write_text("foo:\n  value: 1\nbar:\n  value: 2\n", encoding="utf-8")
        b_path.write_text("baz:\n  value: 3\n", encoding="utf-8")
        original = config_hash(["a.yaml", "b.yaml"], repo_root=tmp_path)

        a_path.write_text("foo:\n  value: 1\n", encoding="utf-8")
        b_path.write_text("baz:\n  value: 3\nbar:\n  value: 2\n", encoding="utf-8")
        moved = config_hash(["a.yaml", "b.yaml"], repo_root=tmp_path)

        assert original != moved

    def test_adding_a_comment_does_not_change_the_hash(self, tmp_path):
        a_path = tmp_path / "a.yaml"
        a_path.write_text("foo:\n  value: 1\n", encoding="utf-8")
        before = config_hash(["a.yaml"], repo_root=tmp_path)

        a_path.write_text("# a comment explaining foo\nfoo:\n  value: 1\n", encoding="utf-8")
        after = config_hash(["a.yaml"], repo_root=tmp_path)

        assert before == after

    def test_whitespace_reformatting_does_not_change_the_hash(self, tmp_path):
        a_path = tmp_path / "a.yaml"
        a_path.write_text("foo:\n  value: 1\n  unit: x\n", encoding="utf-8")
        before = config_hash(["a.yaml"], repo_root=tmp_path)

        a_path.write_text("foo:\n    unit: x\n    value: 1\n", encoding="utf-8")
        after = config_hash(["a.yaml"], repo_root=tmp_path)

        assert before == after

    def test_config_hash_is_stable_across_repeated_calls(self):
        assert config_hash() == config_hash()

    def test_build_hash_changes_with_head_but_config_hash_does_not(self, monkeypatch):
        import eval.provenance as provenance_module

        monkeypatch.setattr(provenance_module, "_git_head_and_dirty", lambda repo_root: ("headA", False))
        hash_a = build_hash()
        config_before = config_hash()

        monkeypatch.setattr(provenance_module, "_git_head_and_dirty", lambda repo_root: ("headB", False))
        hash_b = build_hash()
        config_after = config_hash()

        assert hash_a != hash_b
        assert config_before == config_after

    def test_features_yaml_is_covered_by_config_hash(self):
        # Source: Day-5 Plan Step 1 -- config/features.yaml is a build input
        # (model/audit/calibration knobs) and must be provenanced. Additive
        # test; no existing assertion edited (§11/R2).
        from eval.provenance import DEFAULT_CONFIG_PATHS

        assert "config/features.yaml" in DEFAULT_CONFIG_PATHS

    def test_editing_features_yaml_changes_the_config_hash(self, tmp_path):
        # Source: Day-5 Plan Step 1 -- the audit threshold / model params /
        # calibration flags in config/features.yaml participate in config_hash.
        import eval.provenance as provenance
        from eval.provenance import DEFAULT_CONFIG_PATHS

        for rel in DEFAULT_CONFIG_PATHS:
            src = provenance.REPO_ROOT / rel
            dst = tmp_path / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        before = config_hash(list(DEFAULT_CONFIG_PATHS), repo_root=tmp_path)
        feats = tmp_path / "config" / "features.yaml"
        feats.write_text(
            feats.read_text(encoding="utf-8").replace("value: 0.95", "value: 0.90"),
            encoding="utf-8",
        )
        after = config_hash(list(DEFAULT_CONFIG_PATHS), repo_root=tmp_path)
        assert before != after
