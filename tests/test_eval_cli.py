import json

from lisa.eval import cli as eval_cli


def test_eval_cli_requires_prediction_file(mini_data, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LISA_DATA_DIR", str(mini_data))
    monkeypatch.setenv("LISA_OUT_DIR", str(tmp_path / "out"))
    assert eval_cli.main([]) == 2
    assert "run scripts/extract_llm.py --dataset gold_eval first" in capsys.readouterr().err


def test_eval_cli_on_real_gold_vs_itself(real_data_dir, tmp_path, monkeypatch):
    """Feeding the gold back as the prediction must score 1.0 everywhere (sanity check of the whole eval path)."""
    monkeypatch.setenv("LISA_OUT_DIR", str(tmp_path / "out"))
    units = []
    for f in sorted((real_data_dir / "gold_standard").glob("*.json")):
        g = json.loads(f.read_text(encoding="utf-8"))
        units.append({"unit_id": g["unit_id"], "case_id": g["case_id"], "dataset": g["provenance"]["dataset"],
                      "status": "ok", "nodes": [{**n, "provenance": "llm"} for n in g["nodes"]],
                      "edges": [{**e, "provenance": "llm"} for e in g["edges"]]})
    out = tmp_path / "out"
    out.mkdir()
    (out / "llm_gold_eval.json").write_text(json.dumps({"model": "gold", "prompt_versions": {}, "units": units,
                                                        "pending": []}), encoding="utf-8")
    assert eval_cli.main([]) == 0
    rep = json.loads((out / "eval" / "extraction_report.json").read_text(encoding="utf-8"))
    assert rep["scored_units"] == 23
    for k in ("nodes_strict", "edges_strict"):
        assert rep["headline"]["micro"][k]["f1"] >= 0.99, k
    assert (out / "eval" / "extraction_report.md").exists()
