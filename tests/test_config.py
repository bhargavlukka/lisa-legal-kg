import pytest

from lisa.common.config import load_dataset, load_eval_settings, load_llm_settings, load_settings


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



def test_llm_settings_from_yaml_and_env(monkeypatch, tmp_path):
    (tmp_path / "settings.yaml").write_text(
        "llm:\n  base_url: https://x/v1\n  model: m-1\n  window_pages: 4\neval:\n  match_threshold: 0.4\n"
        "  fewshot_units: [a__u1of1]\n", encoding="utf-8")
    monkeypatch.setenv("SHAREDLLM_API_KEY", "sek")
    s = load_llm_settings(config_dir=tmp_path, env_file=None)
    assert (s.base_url, s.model, s.api_key, s.window_pages, s.temperature) == ("https://x/v1", "m-1", "sek", 4, 0.0)
    assert s.max_requests_per_run == 300 and s.include_unverified_in_graph is False and s.json_mode is True
    e = load_eval_settings(config_dir=tmp_path)
    assert e.match_threshold == 0.4 and e.fewshot_units == ("a__u1of1",)


def test_repo_llm_settings_have_model_and_fewshot(monkeypatch):
    monkeypatch.delenv("SHAREDLLM_API_KEY", raising=False)
    s = load_llm_settings(env_file=None)
    assert s.model == "z-ai/glm-flash-latest" and s.api_key is None
    assert load_eval_settings().fewshot_units == ("eoir_4018__u1of1", "scotus_2017_17-269__u1of1")
