"""Config loader. Everything domain-specific comes from YAML; secrets come from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"


@dataclass(frozen=True)
class Source:
    path: str
    domain: str
    fields: dict[str, str]
    extra: list[str] = field(default_factory=list)
    statute_patterns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DatasetConfig:
    name: str
    sources: list[Source]
    cross_domain: list[tuple[str, str]]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    out_dir: Path
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str | None


def _yaml(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_settings(config_dir: Path = CONFIG_DIR, env_file: Path | None = REPO_ROOT / ".env") -> Settings:
    if env_file is not None:
        load_dotenv(env_file)
    s = _yaml(config_dir / "settings.yaml")
    raw = os.environ.get("LISA_DATA_DIR")
    if not raw:
        raise RuntimeError("LISA_DATA_DIR is not set (copy .env.example to .env)")
    data_dir = Path(raw)
    if not data_dir.is_dir():
        raise RuntimeError(f"LISA_DATA_DIR does not exist: {data_dir}")
    out_dir = Path(os.environ.get("LISA_OUT_DIR") or REPO_ROOT / s.get("out_dir", "out"))
    return Settings(
        data_dir=data_dir,
        out_dir=out_dir,
        neo4j_uri=os.environ.get("NEO4J_URI") or s.get("neo4j_uri", "bolt://localhost:7687"),
        neo4j_user=os.environ.get("NEO4J_USER", "neo4j"),
        neo4j_password=os.environ.get("NEO4J_PASSWORD"),
    )


def load_dataset(name: str, config_dir: Path = CONFIG_DIR) -> DatasetConfig:
    d = _yaml(config_dir / "datasets" / f"{name}.yaml")
    sources = []
    for s in d["sources"]:
        dom = _yaml(config_dir / "domains" / f"{s['domain']}.yaml")
        sources.append(Source(
            path=s["path"],
            domain=s["domain"],
            fields=dict(dom["fields"]),
            extra=list(dom.get("extra") or []),
            statute_patterns=list(dom.get("statute_patterns") or []),
        ))
    cross = [(c["from_domain"], c["to_domain"]) for c in d.get("cross_domain") or []]
    return DatasetConfig(name=d["name"], sources=sources, cross_domain=cross)
