import pytest

from lisa.common.config import load_dataset, load_settings


def test_load_dataset_all_has_both_sources_and_cross_rule():
    ds = load_dataset("all")
    assert ds.name == "all"
    assert [s.domain for s in ds.sources] == ["immigration", "litigation"]
    assert ds.cross_domain == [("immigration", "litigation")]
    assert ds.sources[0].fields["court"] == "issuing_body"
    assert ds.sources[1].fields["court"] == "court"
    assert "ina_section" in ds.sources[0].statute_patterns
    assert "ina_section" not in ds.sources[1].statute_patterns


def test_new_domain_needs_only_yaml(tmp_path):
    (tmp_path / "domains").mkdir()
    (tmp_path / "datasets").mkdir()
    (tmp_path / "domains" / "tax.yaml").write_text(
        "domain: tax\nfields: {id: case_no, title: name, citation: cite}\nstatute_patterns: [usc]\n",
        encoding="utf-8")
    (tmp_path / "datasets" / "tax.yaml").write_text(
        "name: tax\nsources:\n  - {path: tax.jsonl, domain: tax}\n", encoding="utf-8")
    ds = load_dataset("tax", config_dir=tmp_path)
    assert ds.sources[0].fields["id"] == "case_no"
    assert ds.sources[0].extra == []
    assert ds.cross_domain == []


def test_settings_requires_data_dir(monkeypatch):
    monkeypatch.delenv("LISA_DATA_DIR", raising=False)
    with pytest.raises(RuntimeError, match="LISA_DATA_DIR"):
        load_settings(env_file=None)


def test_settings_rejects_missing_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LISA_DATA_DIR", str(tmp_path / "nope"))
    with pytest.raises(RuntimeError, match="does not exist"):
        load_settings(env_file=None)


def test_settings_out_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("LISA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LISA_OUT_DIR", str(tmp_path / "o"))
    s = load_settings(env_file=None)
    assert s.data_dir == tmp_path and s.out_dir == tmp_path / "o"
