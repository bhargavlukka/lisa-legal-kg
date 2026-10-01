import json

from lisa.graph.cli import main


def test_cli_builds_checks_and_writes_json(mini_data, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LISA_DATA_DIR", str(mini_data))
    monkeypatch.setenv("LISA_OUT_DIR", str(tmp_path / "out"))
    assert main(["--dataset", "all", "--check", "--no-load"]) == 0
    g = json.loads((tmp_path / "out" / "graph_all.json").read_text(encoding="utf-8"))
    assert len([n for n in g["nodes"] if n["label"] == "Case"]) == 3
    assert json.loads((tmp_path / "out" / "quarantine_all.json").read_text(encoding="utf-8")) == []
    assert "missing 0" in capsys.readouterr().out


def test_cli_bad_data_dir_is_clean_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LISA_DATA_DIR", str(tmp_path / "missing"))
    assert main(["--dataset", "all", "--no-load"]) == 2
    assert "config error" in capsys.readouterr().err


def test_cli_checksum_error_is_clean_error(mini_data, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LISA_DATA_DIR", str(mini_data))
    monkeypatch.setenv("LISA_OUT_DIR", str(tmp_path / "out"))
    p = mini_data / "pack_litigation" / "records.jsonl"
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert main(["--dataset", "all", "--no-load"]) == 2
    assert "checksum error" in capsys.readouterr().err


def test_cli_data_dir_without_manifest_is_clean_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LISA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LISA_OUT_DIR", str(tmp_path / "out"))
    assert main(["--dataset", "all", "--no-load"]) == 2
    assert "manifest.json" in capsys.readouterr().err


def test_cli_unknown_dataset_is_clean_error(mini_data, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LISA_DATA_DIR", str(mini_data))
    assert main(["--dataset", "bogus", "--no-load"]) == 2
    assert "bogus" in capsys.readouterr().err
