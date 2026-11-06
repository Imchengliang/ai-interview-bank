"""Configuration loading. All paths resolve relative to the package root."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_CONFIG = PACKAGE_ROOT / "config.example.json"
LOCAL_CONFIG = PACKAGE_ROOT / "config.json"

ENTITY_TERMS = [
    "RAG", "Rerank", "Agent", "ReAct", "LangGraph", "LangChain", "MCP",
    "Function Calling", "Prompt", "Checkpoint", "State", "Reducer", "Skill",
    "Redis", "SSE", "WebSocket", "Docker", "沙箱", "向量库", "Embedding",
    "幻觉", "评测集", "Token", "上下文", "意图识别", "缓存", "并发",
]

DEFAULT_MODES = {
    "m0_manual_link": True,       # P0: the only enabled source
    "m1_keyword_scan": False,
    "m2_creator_watch": False,
    "m3_collection_import": False,
    "m4_forward_inbox": False,
    "m5_cross_platform": False,
    "m6_graph_gap_probe": False,
    "m7_comment_harvest": False,
    "m8_digest": False,
}


@dataclass
class Config:
    bank_path: Path
    write_policy: str = "preview-confirm"
    modes: dict = field(default_factory=lambda: dict(DEFAULT_MODES))
    state_dir: Path = PACKAGE_ROOT / "state"
    graph_dir: Path = PACKAGE_ROOT / "graph"
    entity_terms: list[str] = field(default_factory=lambda: list(ENTITY_TERMS))

    @classmethod
    def from_dict(cls, raw: dict) -> "Config":
        def resolve(value: str | Path) -> Path:
            path = Path(value).expanduser()
            return path if path.is_absolute() else (PACKAGE_ROOT / path).resolve()

        modes = dict(DEFAULT_MODES)
        modes.update(raw.get("modes", {}) or {})
        return cls(
            bank_path=resolve(raw.get("bank_path", "~/Documents/interview/ai_question.md")),
            write_policy=raw.get("write_policy", "preview-confirm"),
            modes=modes,
            state_dir=resolve(raw.get("state_dir", "state")),
            graph_dir=resolve(raw.get("graph_dir", "graph")),
            entity_terms=list(raw.get("entity_terms") or ENTITY_TERMS),
        )

    def to_dict(self) -> dict:
        return {
            "bank_path": str(self.bank_path),
            "write_policy": self.write_policy,
            "modes": self.modes,
            "state_dir": str(self.state_dir),
            "graph_dir": str(self.graph_dir),
            "entity_terms": self.entity_terms,
        }

    @property
    def cursor_path(self) -> Path:
        return self.state_dir / "processed_sources.json"

    @property
    def preview_path(self) -> Path:
        return self.state_dir / "previews.json"

    def enabled_modes(self) -> list[str]:
        return [name for name, enabled in self.modes.items() if enabled]


def load_config(path: Path | None = None) -> tuple[Config, Path]:
    """Return (config, config_path). Falls back to the example config."""
    target = Path(path).expanduser() if path else LOCAL_CONFIG
    if not target.exists():
        target = EXAMPLE_CONFIG
    raw = json.loads(target.read_text(encoding="utf-8"))
    return Config.from_dict(raw), target


def ensure_dirs(cfg: Config) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.graph_dir.mkdir(parents=True, exist_ok=True)
