"""Prepare a Socratic practice session from an existing bank question.

Adapted from rederive's idea: hide the answer, make the learner re-derive it
by solving a problem and answering one added constraint at a time.

This module does NO pedagogical writing and NO inference. It only extracts
the raw material that already exists in the bank:
  - 考什么  -> the root problem the interviewer is probing
  - 解题思路 -> the ordered steps the learner should re-derive, one per round
  - 参考答案 -> the reveal, shown only after the learner finishes

The LLM is responsible for turning each step into a constraint-style question
without leaking the answer. See SKILL.md "练习模式".
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from .bank import BankSnapshot, Question, parse_bank
from .config import Config

STEP_LINE_RE = re.compile(r"^\s*(\d+)[.、)]\s*(.*)$")


@dataclass
class CoachPlan:
    qid: str
    category: str
    topic: str
    status: str
    root_probe: str
    steps: list[dict]
    answer: str
    related: list[str]

    def public(self) -> dict:
        """View given to the LLM. Answer is present but marked reveal-only."""
        return {
            "qid": self.qid,
            "category": self.category,
            "topic": self.topic,
            "status": self.status,
            "root_probe": self.root_probe,
            "steps": self.steps,
            "reveal_only": {"answer": self.answer, "related": self.related},
            "_rule": "Never show reveal_only to the user until the derivation is done.",
        }


def _split_steps(text: str) -> list[dict]:
    """Split a numbered 解题思路 field into ordered step dicts."""
    steps = []
    for line in text.splitlines():
        m = STEP_LINE_RE.match(line)
        if m:
            steps.append({"n": int(m.group(1)), "point": m.group(2).strip()})
    if not steps:
        # Fall back to non-empty lines if the author used plain lines.
        steps = [{"n": i, "point": ln.strip()}
                 for i, ln in enumerate(
                     [x for x in text.splitlines() if x.strip()], 1)]
    return steps


def build_plan(q: Question) -> CoachPlan:
    fields = q.fields
    steps = _split_steps(fields.get("解题思路", ""))
    return CoachPlan(
        qid=q.id,
        category=q.category,
        topic=q.topic,
        status=q.status,
        root_probe=fields.get("考什么", ""),
        steps=steps,
        answer=fields.get("参考答案", ""),
        related=q.relations,
    )


def pick_question(snapshot: BankSnapshot, qid: str | None = None,
                  category: str | None = None) -> Question:
    """Pick a question by id, or randomly (optionally within a category)."""
    if qid:
        qid = qid.upper()
        for q in snapshot.questions:
            if q.id == qid:
                return q
        raise ValueError(f"题目不存在: {qid}")
    pool = [q for q in snapshot.questions
            if q.status == "已分析" and q.fields.get("参考答案")]
    if category:
        filtered = [q for q in pool if category in q.category]
        if not filtered:
            raise ValueError(f"该类别无已分析题目: {category}")
        pool = filtered
    if not pool:
        raise ValueError("题库里没有可用于练习的已分析题目")
    return random.choice(pool)


def plan(cfg: Config, qid: str | None = None, category: str | None = None,
         list_ids: bool = False) -> dict:
    snapshot = parse_bank(cfg.bank_path)
    if list_ids:
        usable = [q.id for q in snapshot.questions
                  if q.status == "已分析" and q.fields.get("参考答案")]
        return {"total": len(usable), "qids": usable}
    q = pick_question(snapshot, qid, category)
    return build_plan(q).public()
