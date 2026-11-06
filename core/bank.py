"""Read, validate and stage questions in the single-source ai_question.md.

Fenced example blocks are ignored (the bank contains a format sample).
This module never writes answers; it only stages question headers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

HEADER_RE = re.compile(r"^####\s+Q(\d{3,})\s*·\s*(.*?)\s*·\s*状态：\s*(\S+)")
SECTION_RE = re.compile(r"^###\s+(\d+)\.\s+(.*)$")
FIELD_RE = re.compile(r"^\*\*(题目|关联|考什么|解题思路|参考答案)\*\*[：:]\s*(.*)$")
RELATED_ID_RE = re.compile(r"Q(\d{3,})")


@dataclass
class Question:
    id: str
    category: str
    status: str
    section: str = ""
    fields: dict = field(default_factory=dict)
    raw: str = ""

    @property
    def topic(self) -> str:
        return self.fields.get("题目", "")

    @property
    def relations(self) -> list[str]:
        return [f"Q{n}" for n in RELATED_ID_RE.findall(self.fields.get("关联", ""))]

    @property
    def answered(self) -> bool:
        return self.status == "已分析" and "参考答案" in self.fields


@dataclass
class BankSnapshot:
    path: Path
    text: str
    sections: dict = field(default_factory=dict)
    questions: list = field(default_factory=list)

    @property
    def next_id(self) -> str:
        max_id = max((int(q.id[1:]) for q in self.questions), default=0)
        return f"Q{max_id + 1:03d}"

    @property
    def ids(self) -> set[str]:
        return {q.id for q in self.questions}

    @property
    def empty_sections(self) -> list[str]:
        return [num for num, count in _section_counts(self).items() if count == 0]


def _section_counts(snapshot: BankSnapshot) -> dict:
    counts = {num: 0 for num in snapshot.sections}
    for q in snapshot.questions:
        if q.section in counts:
            counts[q.section] += 1
    return counts


def parse_bank(path: Path) -> BankSnapshot:
    """Parse the bank into sections and question blocks, skipping code fences."""
    if not path.exists():
        raise FileNotFoundError(f"BANK_MISSING: {path}")
    text = path.read_text(encoding="utf-8")
    snap = BankSnapshot(path=path, text=text)
    lines = text.splitlines(keepends=True)
    in_code = False
    current_section = ""
    current: Question | None = None
    block: list[str] = []

    def close() -> None:
        nonlocal current, block
        if current is not None:
            current.raw = "".join(block)
            snap.questions.append(current)
        current, block = None, []

    for line in lines:
        if line.lstrip().startswith("```"):
            in_code = not in_code
            if current is not None:
                block.append(line)
            continue
        if in_code:
            if current is not None:
                block.append(line)
            continue

        section = SECTION_RE.match(line)
        if section:
            close()
            current_section = section.group(1)
            snap.sections[current_section] = section.group(2).strip()
            continue

        header = HEADER_RE.match(line)
        if header:
            close()
            current = Question(
                id=f"Q{int(header.group(1)):03d}",
                category=header.group(2).strip(),
                status=header.group(3).strip(),
                section=current_section,
            )
            block = [line]
            continue

        if current is not None:
            block.append(line)
            matched = FIELD_RE.match(line)
            if matched:
                current.fields[matched.group(1)] = matched.group(2).strip()
    close()
    return snap


def verify(snapshot: BankSnapshot) -> dict:
    """Structural integrity check used by `cli verify` and `finalize`."""
    ids = [q.id for q in snapshot.questions]
    dupes = sorted({qid for qid in ids if ids.count(qid) > 1})
    missing = []
    for q in snapshot.questions:
        # 待分析题刚入库时只有题头（题目 + 关联）；答案由 Step 4 补写。
        required = (("题目", "关联") if q.status == "待分析"
                    else ("题目", "关联", "考什么", "参考答案"))
        for field_name in required:
            if not q.fields.get(field_name):
                missing.append(f"{q.id}:{field_name}")
    pending = [q.id for q in snapshot.questions if q.status == "待分析"]
    bad_status = [q.id for q in snapshot.questions
                  if q.status not in ("待分析", "已分析")]
    return {
        "total": len(ids),
        "next_id": snapshot.next_id,
        "duplicate_ids": dupes,
        "missing_fields": missing,
        "pending": pending,
        "bad_status": bad_status,
        "empty_sections": snapshot.empty_sections,
        "ok": not (dupes or missing or bad_status),
    }


@dataclass
class NewQuestion:
    category: str
    topic: str
    relation: str = "无"

    def block(self, qid: str) -> str:
        return (
            f"#### {qid} · {self.category} · 状态：待分析\n"
            f"**题目**：{self.topic}\n"
            f"**关联**：{self.relation}\n\n"
        )


def stage_questions(snapshot: BankSnapshot, items: list[NewQuestion],
                    dry_run: bool = True) -> dict:
    """Insert question headers at the end of each category section.

    Only headers are written: answers remain the LLM's job (Step 4).
    Existing question text is never modified.
    """
    category_to_section = {name: num for num, name in snapshot.sections.items()}
    grouped: dict[str, list[str]] = {}
    next_num = int(snapshot.next_id[1:])
    assignments = []
    for item in items:
        if item.category not in category_to_section:
            raise ValueError(f"unknown category: {item.category}")
        qid = f"Q{next_num:03d}"
        next_num += 1
        assignments.append({"id": qid, "category": item.category,
                            "topic": item.topic})
        grouped.setdefault(category_to_section[item.category], []).append(
            item.block(qid)
        )

    if dry_run:
        return {"dry_run": True, "assignments": assignments, "text": snapshot.text}

    text = snapshot.text
    for section_num, blocks in grouped.items():
        marker = None
        for num, name in snapshot.sections.items():
            if num == section_num:
                marker = f"### {num}. {name}"
                break
        if marker is None or text.count(marker) != 1:
            raise ValueError(f"section anchor not unique: {marker}")
        start = text.index(marker) + len(marker)
        following = [text.find(f"\n### {n}. ", start)
                     for n in snapshot.sections if int(n) > int(section_num)]
        following = [p for p in following if p >= 0]
        end = min(following) if following else text.find("\n## ", start)
        if end < 0:
            end = len(text)
        chunk = text[start:end]
        chunk = chunk.replace("_暂无题目_", "").rstrip() + "\n\n"
        text = text[:start] + chunk + "".join(blocks) + text[end:]

    return {"dry_run": False, "assignments": assignments, "text": text}


def write_bank(path: Path, text: str) -> None:
    """Overwrite the single source. Callers must have passed verify()."""
    path.write_text(text, encoding="utf-8")


def search(snapshot: BankSnapshot, query: str, limit: int = 20) -> list[dict]:
    needle = query.lower()
    hits = []
    for q in snapshot.questions:
        haystack = " ".join([q.topic, q.fields.get("考什么", ""),
                             q.fields.get("关联", ""),
                             q.fields.get("参考答案", "")]).lower()
        if needle in haystack:
            hits.append({"id": q.id, "category": q.category,
                         "status": q.status, "topic": q.topic})
        if len(hits) >= limit:
            break
    return hits
