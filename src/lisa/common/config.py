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


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    model: str
    api_key: str | None
    temperature: float
    max_output_tokens: int
    timeout_s: float
    max_requests_per_run: int
    window_pages: int
    edge_split_chars: int
    include_unverified_in_graph: bool
    json_mode: bool
    auth: str = "sharedllm"                  # sharedllm: X-SharedLLM-Key header | bearer: Authorization: Bearer
    api_key_env: str = "SHAREDLLM_API_KEY"   # | sharedllm_byok: X-SharedLLM-Key + provider key as Bearer
    provider_key: str | None = None
    provider_key_env: str | None = None
    workers: int = 1                         # parallel LLM requests per run


@dataclass(frozen=True)
class EvalSettings:
    match_threshold: float
    fewshot_units: tuple[str, ...]


def load_llm_settings(config_dir: Path = CONFIG_DIR, env_file: Path | None = REPO_ROOT / ".env") -> LLMSettings:
    if env_file is not None:
        load_dotenv(env_file)
    s = _yaml(config_dir / "settings.yaml").get("llm") or {}
    key_env = s.get("api_key_env", "SHAREDLLM_API_KEY")
    return LLMSettings(
        base_url=s["base_url"],
        model=s["model"],
        api_key=os.environ.get(key_env) or None,
        temperature=float(s.get("temperature", 0)),
        max_output_tokens=int(s.get("max_output_tokens", 8192)),
        timeout_s=float(s.get("timeout_s", 180)),
        max_requests_per_run=int(s.get("max_requests_per_run", 300)),
        window_pages=int(s.get("window_pages", 3)),
        edge_split_chars=int(s.get("edge_split_chars", 60000)),
        include_unverified_in_graph=bool(s.get("include_unverified_in_graph", False)),
        json_mode=bool(s.get("json_mode", True)),
        auth=s.get("auth", "sharedllm"),
        api_key_env=key_env,
        provider_key=os.environ.get(s["provider_key_env"]) or None if s.get("provider_key_env") else None,
        provider_key_env=s.get("provider_key_env"),
        workers=max(1, int(s.get("workers", 1))),
    )


def load_eval_settings(config_dir: Path = CONFIG_DIR) -> EvalSettings:
    s = _yaml(config_dir / "settings.yaml").get("eval") or {}
    return EvalSettings(match_threshold=float(s.get("match_threshold", 0.3)),
                        fewshot_units=tuple(s.get("fewshot_units") or ()))


@dataclass(frozen=True)
class ServeSettings:
    dataset: str
    llm_graphs: tuple[str, ...]
    backend: str
    host: str
    ports: dict[str, int]


@dataclass(frozen=True)
class AuthSettings:
    issuer: str
    audience: str
    token_ttl_s: int
    secret: str | None


@dataclass(frozen=True)
class CourtListenerSettings:
    base_url: str
    token: str | None
    per_minute: int
    per_hour: int
    per_day: int
    timeout_s: float
    max_retries: int


def load_serve_settings(config_dir: Path = CONFIG_DIR) -> ServeSettings:
    s = _yaml(config_dir / "settings.yaml").get("serve") or {}
    ports = {"graph": 8101, "verifier": 8102, "analytics": 8103, "external": 8104, **(s.get("ports") or {})}
    return ServeSettings(dataset=os.environ.get("LISA_SERVE_DATASET") or s.get("dataset", "all"),
                         llm_graphs=tuple(s.get("llm_graphs") or ()),
                         backend=os.environ.get("LISA_GRAPH_BACKEND") or s.get("backend", "memory"),
                         host=os.environ.get("LISA_HOST") or s.get("host", "127.0.0.1"),
                         ports={k: int(v) for k, v in ports.items()})


def load_auth_settings(config_dir: Path = CONFIG_DIR, env_file: Path | None = REPO_ROOT / ".env") -> AuthSettings:
    if env_file is not None:
        load_dotenv(env_file)
    s = _yaml(config_dir / "settings.yaml").get("auth") or {}
    return AuthSettings(issuer=s.get("issuer", "lisa-auth"), audience=s.get("audience", "lisa-mcp"),
                        token_ttl_s=int(s.get("token_ttl_s", 28800)),
                        secret=os.environ.get(s.get("secret_env", "LISA_AUTH_SECRET")) or None)


def load_courtlistener_settings(config_dir: Path = CONFIG_DIR,
                                env_file: Path | None = REPO_ROOT / ".env") -> CourtListenerSettings:
    if env_file is not None:
        load_dotenv(env_file)
    s = _yaml(config_dir / "settings.yaml").get("courtlistener") or {}
    lim = s.get("limits") or {}
    return CourtListenerSettings(
        base_url=s.get("base_url", "https://www.courtlistener.com/api/rest/v4").rstrip("/"),
        token=os.environ.get(s.get("token_env", "COURTLISTENER_TOKEN")) or None,
        per_minute=int(lim.get("per_minute", 5)), per_hour=int(lim.get("per_hour", 50)),
        per_day=int(lim.get("per_day", 125)), timeout_s=float(s.get("timeout_s", 30)),
        max_retries=int(s.get("max_retries", 3)))


@dataclass(frozen=True)
class AgentSettings:
    base_url: str
    model: str
    gateway_key: str | None
    provider_key: str | None
    max_turns: int
    max_revisions: int
    sessions_dir: str


def load_agent_settings(config_dir: Path = CONFIG_DIR, env_file: Path | None = REPO_ROOT / ".env") -> AgentSettings:
    llm = load_llm_settings(config_dir, env_file)
    s = _yaml(config_dir / "settings.yaml").get("agent") or {}
    return AgentSettings(base_url=s.get("base_url", "https://api.sharedllm.com/ollama"),
                         model=os.environ.get("LISA_AGENT_MODEL") or s.get("model", llm.model),
                         gateway_key=llm.api_key, provider_key=llm.provider_key,
                         max_turns=int(s.get("max_turns", 30)), max_revisions=int(s.get("max_revisions", 2)),
                         sessions_dir=s.get("sessions_dir", "sessions"))
