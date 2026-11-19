"""Incremental Obsidian vault exporter for ai_question.md.

The bank markdown stays the single source of truth. This module only writes
a derived vault of per-question notes whose wikilinks come straight from the
bank's **关联** field. Hand-written notes are preserved on regeneration.

Design:
- vault root defaults to bank_path.parent / "题库笔记"
- each question becomes Qxxx.md with YAML frontmatter at the very top
- **关联** becomes [[wikilinks]]; categories/entities/angles become hub notes
- a fenced USER NOTES block is preserved verbatim across regenerations
- files are only rewritten when the rendered content actually changes
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .bank import BankSnapshot, parse_bank
from .config import Config
from .graph import build as build_graph

USER_BEGIN = "<!-- USER NOTES: BEGIN -->"
USER_END = "<!-- USER NOTES: END -->"
DEFAULT_VAULT_NAME = "题库笔记"


def default_vault(cfg: Config) -> Path:
    return cfg.bank_path.parent / DEFAULT_VAULT_NAME


def _wikilinks(q, all_ids: set[str]) -> str:
    """Turn '关联：Q019（..）、Q038（..）' into clickable wikilinks."""
    raw = q.fields.get("关联", "").strip()
    if not raw or raw == "无":
        return ""
    out = []
    for part in re.split(r"[、,，;；]\s*", raw):
        m = re.search(r"(Q\d{3,})(.*)", part)
        if not m:
            continue
        qid = m.group(1)
        note = m.group(2).strip().strip("（）()")
        target = qid if qid in all_ids else qid
        out.append(f"- [[{target}]]{(' — ' + note) if note else ''}")
    return "\n".join(out)


def _render_question(q, all_ids: set[str], entities: list[str], angle: str, user_notes: str = "") -> str:
    def yaml_list(items: list[str]) -> str:
        return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in items) + "]" if items else "[]"

    lines = [
        "---",
        f"qid: {q.id}",
        f"title: {json.dumps(q.topic, ensure_ascii=False)}",
        f"category: {json.dumps(q.category, ensure_ascii=False)}",
        f"status: {q.status}",
        f"entity: {yaml_list(entities)}",
        f"angle: {json.dumps(angle, ensure_ascii=False)}",
        "source: ai_question.md",
        "---",
        "",
        f"# {q.id} · {q.topic}",
        "",
        "## 题目",
        "",
        q.topic or "(无题干)",
        "",
        "## 关联",
        "",
        _wikilinks(q, all_ids) or "无",
        "",
    ]
    for field in ("考什么", "解题思路", "参考答案"):
        value = q.fields.get(field, "").strip()
        if value:
            lines += [f"## {field}", "", value, ""]
    lines += [
        "## 我的笔记",
        "",
        USER_BEGIN,
        user_notes.strip("\n"),
        USER_END,
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _extract_user_notes(text: str) -> str:
    if USER_BEGIN not in text or USER_END not in text:
        return ""
    return text.split(USER_BEGIN, 1)[1].split(USER_END, 1)[0]


def _write_if_changed(path: Path, new: str, dry_run: bool) -> str:
    existed = path.exists()
    if existed:
        old = path.read_text(encoding="utf-8")
        if old == new:
            return "unchanged"
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
    return "updated" if existed else "created"


def _hub_note(title: str, kind: str, links: list[str]) -> str:
    body = (
        "---\n"
        f"type: {kind}\n"
        f"title: {json.dumps(title, ensure_ascii=False)}\n"
        "source: ai_question.md\n"
        "---\n\n"
        f"# {kind} · {title}\n\n"
        + "\n".join(f"- [[{qid}]]" for qid in sorted(set(links))) + "\n"
    )
    return body


def graph_css() -> str:
    return """/* ai-interview-bank graph colours */
.graph-view.color-fill { color: #7f8c9b; }
.graph-view.color-circle { color: #4a90d9; }
.graph-view.color-fill-focused { color: #e67e22; }
.graph-view.color-arrow { color: #95a5a6; }
.graph-view.color-text { color: #ecf0f1; }
"""


def _vault_meta(vault: Path, dry_run: bool) -> list[str]:
    written = []
    meta = vault / ".obsidian"
    css = meta / "graph.css"
    if not css.exists():
        if not dry_run:
            meta.mkdir(parents=True, exist_ok=True)
            css.write_text(graph_css(), encoding="utf-8")
        written.append(str(css))
    readme = vault / "README.md"
    if not readme.exists():
        text = (
            "# AI 面试题库 · Obsidian KG\n\n"
            "本目录由 `ai-interview-bank` 从 `ai_question.md` 自动生成。"
            "题目内容请到题库文件修改，改完跑 `python3 cli.py obsidian` 同步。\n\n"
            "- 每篇 `Qxxx.md` 是一道题，`## 关联` 里是到其它题的双链。\n"
            "- `类别-*.md`、`实体-*.md`、`角度-*.md` 是图谱枢纽页。\n"
            "- 每篇笔记末尾「我的笔记」区随便写，重建时不会覆盖。\n"
            "- 打开 Graph View 即可看到题目网络。\n"
        )
        if not dry_run:
            readme.write_text(text, encoding="utf-8")
        written.append(str(readme))
    return written


def sync(cfg: Config, vault: Path | None = None, dry_run: bool = False) -> dict:
    """Create or update the Obsidian vault from the bank. Idempotent."""
    vault = vault or default_vault(cfg)
    snapshot: BankSnapshot = parse_bank(cfg.bank_path)
    all_ids = snapshot.ids

    gr = build_graph(snapshot, cfg)
    entities_by_q: dict[str, list[str]] = {}
    angle_by_q: dict[str, str] = {}
    for e in gr.edges:
        if e["kind"] == "MENTIONS":
            qid = e["source"].split(":", 1)[1]
            entities_by_q.setdefault(qid, []).append(e["target"].split(":", 1)[1])
        elif e["kind"] == "HAS_ANGLE":
            qid = e["source"].split(":", 1)[1]
            angle_by_q[qid] = e["target"].split(":", 1)[1]

    stats = {"vault": str(vault), "questions": len(snapshot.questions),
             "created": 0, "updated": 0, "unchanged": 0,
             "user_notes_preserved": 0, "hubs": 0}

    if not dry_run:
        vault.mkdir(parents=True, exist_ok=True)

    for q in snapshot.questions:
        entities = entities_by_q.get(q.id, [])
        angle = angle_by_q.get(q.id, "其他")
        path = vault / f"{q.id}.md"
        user_notes = _extract_user_notes(path.read_text(encoding="utf-8")) if path.exists() else ""
        if user_notes.strip():
            stats["user_notes_preserved"] += 1
        new = _render_question(q, all_ids, entities, angle, user_notes)
        stats[_write_if_changed(path, new, dry_run)] += 1

    # hub pages: category / entity / angle
    hub_specs: dict[str, tuple[str, list[str]]] = {}
    for q in snapshot.questions:
        hub_specs.setdefault(f"类别-{q.category}", ("类别", []))[1].append(q.id)
    for qid, ents in entities_by_q.items():
        for ent in ents:
            hub_specs.setdefault(f"实体-{ent}", ("实体", []))[1].append(qid)
    for qid, ang in angle_by_q.items():
        hub_specs.setdefault(f"角度-{ang}", ("角度", []))[1].append(qid)

    for name, (kind, links) in hub_specs.items():
        safe = re.sub(r'[\\/:*?"<>|]', "_", name)
        result = _write_if_changed(vault / f"{safe}.md", _hub_note(name.split("-", 1)[1], kind, links), dry_run)
        if result != "unchanged":
            stats["hubs"] += 1

    stats["config"] = {"files": _vault_meta(vault, dry_run)}
    return stats
