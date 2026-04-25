from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

EmbeddingProvider = Literal["Ollama", "OpenAI", "VoyageAI", "Gemini", "OpenRouter"]


class Workspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = "."
    name: str


class Anchors(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_path: str = ".engram/anchors.sqlite"
    reconcile_interval_hours: int = 24
    wal_tailer_poll_ms: int = 500


class SerenaUpstream(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(default_factory=lambda: ["serena", "start-mcp-server"])
    args_extra: list[str] = Field(default_factory=list)
    working_dir: str = "."


class MempalaceUpstream(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(default_factory=lambda: ["mempalace-mcp"])
    palace_path: str = "~/.mempalace/palace"
    wal_path: str = "~/.mempalace/wal/write_log.jsonl"


class ClaudeContextUpstream(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(
        default_factory=lambda: ["npx", "@zilliz/claude-context-mcp@0.1.8"]
    )
    embedding_provider: EmbeddingProvider = "Ollama"
    embedding_model: str = "nomic-embed-text"
    milvus_address: str = "localhost:19530"
    snapshot_path: str = "~/.context/mcp-codebase-snapshot.json"
    merkle_path: str = "~/.context/merkle"
    reindex_tick_seconds: int = 300


class Upstreams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    serena: SerenaUpstream = Field(default_factory=SerenaUpstream)
    mempalace: MempalaceUpstream = Field(default_factory=MempalaceUpstream)
    claude_context: ClaudeContextUpstream = Field(default_factory=ClaudeContextUpstream)


class FusionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm: Literal["rrf"] = "rrf"
    k: int = 60


class CacheTTLs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vec_search: int = 60
    code_find_symbol: int = 30
    mem_search: int = 120
    mem_kg_query: int = 300
    fused: int = 60


class CacheConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ttl_seconds: CacheTTLs = Field(default_factory=CacheTTLs)
    max_entries: int = 1024


class Router(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fusion: FusionConfig = Field(default_factory=FusionConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)


class Logging(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file: str = ".engram/logs/engram.log"


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    workspace: Workspace
    anchors: Anchors = Field(default_factory=Anchors)
    upstreams: Upstreams = Field(default_factory=Upstreams)
    router: Router = Field(default_factory=Router)
    logging: Logging = Field(default_factory=Logging)

    @classmethod
    def load(cls, path: Path) -> Config:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls.model_validate(data)

    def dump(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(self.model_dump(mode="json"), fh, sort_keys=False)


def default_config(workspace_name: str, embedding_provider: EmbeddingProvider) -> Config:
    cfg = Config(workspace=Workspace(name=workspace_name))
    cfg.upstreams.claude_context.embedding_provider = embedding_provider
    return cfg
