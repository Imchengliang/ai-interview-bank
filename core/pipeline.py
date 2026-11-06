"""Pipeline state machine: preview -> confirm -> stage -> (LLM analysis) -> finalize.

Step 1 transcription and Step 2 semantic dedup are LLM work. Step 4 answers are
LLM work. This module only does the mechanical parts and *never* writes answers.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import bank, graph, sources
from .config import Config, ensure_dirs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_previews(cfg: Config) -> dict:
    ensure_dirs(cfg)
    if not cfg.preview_path.exists():
        return {"version": 1, "previews": {}}
    return json.loads(cfg.preview_path.read_text(encoding="utf-8"))


def preview(cfg: Config, candidates: list[sources.Candidate]) -> dict:
    """Read-only: store raw candidates and report what would be processed."""
    ensure_dirs(cfg)
    candidate_dir = cfg.state_dir / "candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    rows, duplicates, needs_manual = [], [], []
    for candidate in candidates:
        (candidate_dir / f"{candidate.source_id}.json").write_text(
            json.dumps(candidate.__dict__, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        row = candidate.summary()
        row["already_processed"] = sources.is_processed(cfg, candidate.source_id)
        rows.append(row)
        if row["already_processed"]:
            duplicates.append(candidate.source_id)
        if candidate.status == "needs_manual":
            needs_manual.append({"source_id": candidate.source_id,
                                 "hint": candidate.hint})
    digest = hashlib.sha256(
        "|".join(sorted(r["source_id"] for r in rows)).encode()).hexdigest()[:8]
    preview_id = f"p-{datetime.now().strftime('%Y%m%d%H%M%S')}-{digest}"
    store = _load_previews(cfg)
    store["previews"][preview_id] = {
        "created_at": _now(), "write_policy": cfg.write_policy,
        "source_ids": [r["source_id"] for r in rows],
        "status": "awaiting_confirmation",
    }
    cfg.preview_path.write_text(
        json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "preview_id": preview_id,
        "write_policy": cfg.write_policy,
        "candidates": rows,
        "already_processed": duplicates,
        "needs_manual": needs_manual,
        "next": "交 LLM 按 SKILL.md 完成 Step 1 转录与 Step 2 语义去重；确认后才调用 stage。",
    }


def get_preview(cfg: Config, preview_id: str) -> dict:
    store = _load_previews(cfg)
    if preview_id not in store["previews"]:
        raise KeyError(f"unknown preview_id: {preview_id}")
    return store["previews"][preview_id]


def stage(cfg: Config, preview_id: str, items: list[dict],
          confirm: bool = False) -> dict:
    """Confirmed Step 3: write question headers only (status 待分析)."""
    record = get_preview(cfg, preview_id)
    if cfg.write_policy == "preview-confirm" and not confirm:
        return {"staged": False, "reason": "write_policy=preview-confirm，需显式 --confirm",
                "preview_id": preview_id}
    if not items:
        return {"staged": False, "reason": "去重后没有新增题目", "preview_id": preview_id}
    snapshot = bank.parse_bank(cfg.bank_path)
    new_items = [bank.NewQuestion(category=i["category"], topic=i["topic"],
                                  relation=i.get("relation", "无")) for i in items]
    result = bank.stage_questions(snapshot, new_items, dry_run=False)
    # verify the staged text before committing it to the single source
    check = bank.verify(_parse_text(result["text"], cfg.bank_path))
    if not check["ok"]:
        return {"staged": False, "reason": "结构校验未通过，未写库", "verify": check}
    bank.write_bank(cfg.bank_path, result["text"])

    candidate_dir = cfg.state_dir / "candidates"
    for source_id in record["source_ids"]:
        path = candidate_dir / f"{source_id}.json"
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            candidate = sources.Candidate(**raw)
            sources.mark_processed(cfg, candidate,
                                   note=f"preview={preview_id}; staged={len(items)}")
    store = _load_previews(cfg)
    store["previews"][preview_id]["status"] = "staged"
    store["previews"][preview_id]["staged_ids"] = [a["id"] for a in result["assignments"]]
    cfg.preview_path.write_text(
        json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "staged": True, "assignments": result["assignments"],
        "next": "按 SKILL.md Step 4 逐题写「考什么/解题思路/参考答案」，"
                "Step 5 更新关联索引与更新日志，然后运行 finalize 刷新图谱。",
        "verify": check,
    }


def _parse_text(text: str, path: Path) -> bank.BankSnapshot:
    """Verify a staged string by temporarily parsing it through a temp file."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                    encoding="utf-8") as handle:
        handle.write(text)
        temp = Path(handle.name)
    try:
        return bank.parse_bank(temp)
    finally:
        temp.unlink(missing_ok=True)


def finalize(cfg: Config) -> dict:
    """Step 5 mechanical tail: integrity check + rebuild graph from the bank.

    The graph is recomputed from the single-source bank; the bank itself is
    never rebuilt. Index/changelog prose remains the LLM's job per SKILL.md.
    """
    snapshot = bank.parse_bank(cfg.bank_path)
    check = bank.verify(snapshot)
    if not check["ok"]:
        return {"finalized": False, "verify": check}
    graph_result = graph.save(cfg, graph.build(snapshot, cfg), snapshot)
    return {"finalized": True, "verify": check, "graph": {
        k: graph_result[k] for k in ("json", "mermaid", "gaps", "nodes", "edges")}}


def status(cfg: Config) -> dict:
    snapshot = bank.parse_bank(cfg.bank_path)
    check = bank.verify(snapshot)
    return {
        "bank": str(cfg.bank_path),
        "write_policy": cfg.write_policy,
        "enabled_modes": cfg.enabled_modes(),
        "available_adapters": sources.available_adapters(),
        "questions": check["total"], "next_id": check["next_id"],
        "pending": check["pending"], "empty_sections": check["empty_sections"],
        "processed_sources": len(sources.load_cursor(cfg)["processed"]),
        "graph_ready": (cfg.graph_dir / "knowledge_graph.json").exists(),
    }
