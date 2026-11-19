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


def _usable(snapshot: BankSnapshot) -> list[Question]:
    return [q for q in snapshot.questions
            if q.status == "已分析" and q.fields.get("参考答案")]


def match_categories(snapshot: BankSnapshot, text: str) -> list[str]:
    """Resolve a loose category hint ('RAG', '5', 'agent') to real category names."""
    needle = text.strip().lower()
    names = sorted({q.category for q in snapshot.questions})
    hits = [n for n in names if needle in n.lower()]
    if hits:
        return hits
    # allow the section number, e.g. "4" or "第4类"
    m = re.search(r"\d+", needle)
    if m and m.group(0) in snapshot.sections:
        return [snapshot.sections[m.group(0)]]
    return []


def score_question(q: Question, terms: list[str]) -> int:
    """Rank a question against free-text terms.

    Title beats probe beats answer, and matching more of the terms beats
    matching one of them: a query like "MCP 套壳" should not rank a question
    that only matched "MCP" above one that matched both ideas.
    """
    topic = q.topic.lower()
    probe = q.fields.get("考什么", "").lower()
    answer = q.fields.get("参考答案", "").lower()
    related = q.fields.get("关联", "").lower()
    raw = 0
    hit = 0
    for term in terms:
        got = 0
        if term in topic:
            got = 12
        elif term in probe:
            got = 6
        elif term in answer:
            got = 3
        elif term in related:
            got = 2
        elif 2 <= len(term) <= 8:
            # Tolerate near-misses on the title/probe only. Answer text is long
            # enough that common characters give false positives, so it is
            # excluded here.
            for hay, weight in ((topic, 8), (probe, 4)):
                if not hay:
                    continue
                coverage = sum(1 for ch in term if ch in hay) / len(term)
                if coverage >= 0.9:
                    got = max(got, weight // 2)
        raw += got
        if got:
            hit += 1
    if not raw:
        return 0
    # Reward covering more of the query instead of one lucky keyword.
    coverage = hit / len(terms)
    return int(raw * (0.55 + 0.45 * coverage))


def find_questions(snapshot: BankSnapshot, text: str, limit: int = 8) -> list[tuple[Question, int]]:
    terms = [t for t in re.split(r"[\s,，、]+", text.lower()) if t]
    if not terms:
        return []
    scored = [(q, score_question(q, terms)) for q in _usable(snapshot)]
    scored = [(q, s) for q, s in scored if s > 0]
    scored.sort(key=lambda pair: (-pair[1], pair[0].id))
    return scored[:limit]


def pick_question(snapshot: BankSnapshot, qid: str | None = None,
                  category: str | None = None) -> Question:
    """Pick a question by id, or randomly (optionally within categories)."""
    if qid:
        qid = qid.upper()
        for q in snapshot.questions:
            if q.id == qid:
                return q
        raise ValueError(f"题目不存在: {qid}")
    pool = _usable(snapshot)
    if category:
        names = match_categories(snapshot, category)
        if not names:
            available = sorted({q.category for q in snapshot.questions})
            raise ValueError(f"没有匹配的类别: {category}；可用类别: {'、'.join(available)}")
        filtered = [q for q in pool if q.category in names]
        if not filtered:
            raise ValueError(f"该类别无已分析题目: {'、'.join(names)}")
        pool = filtered
    if not pool:
        raise ValueError("题库里没有可用于练习的已分析题目")
    return random.choice(pool)


def plan(cfg: Config, qid: str | None = None, category: str | None = None,
         find: str | None = None, list_ids: bool = False,
         list_category: str | None = None) -> dict:
    snapshot = parse_bank(cfg.bank_path)

    if list_ids:
        pool = _usable(snapshot)
        if list_category:
            names = match_categories(snapshot, list_category)
            if not names:
                raise ValueError(f"没有匹配的类别: {list_category}")
            pool = [q for q in pool if q.category in names]
            return {"category": names, "total": len(pool),
                    "questions": [{"id": q.id, "topic": q.topic} for q in pool]}
        counts: dict[str, int] = {}
        for q in pool:
            counts[q.category] = counts.get(q.category, 0) + 1
        return {"total": len(pool), "qids": [q.id for q in pool],
                "by_category": counts}

    if find:
        ranked = find_questions(snapshot, find)
        if not ranked:
            raise ValueError(f"没有匹配「{find}」的已分析题目，换个关键词或先 --list 看看")
        best, best_score = ranked[0]
        # A clear winner is returned directly; close contenders are surfaced so
        # the agent can ask the user which one they meant.
        contenders = [{"id": q.id, "topic": q.topic, "category": q.category,
                       "score": s} for q, s in ranked[1:] if s >= best_score * 0.6]
        payload = build_plan(best).public()
        payload["matched_by"] = {"find": find, "score": best_score}
        if contenders:
            payload["ambiguous"] = True
            payload["candidates"] = contenders
            payload["_rule_ambiguous"] = (
                "关键词匹配只是初筛。先按语义看候选里哪道才是用户说的那道："
                "如果你的判断与默认的最佳匹配不同，直接用候选里更贴切的那道；"
                "如果确实拿不准，就把 2–3 个候选的题目列给用户选，再开始引导。"
                "不要在没有把握时硬选一道。")
        return payload

    q = pick_question(snapshot, qid, category)
    payload = build_plan(q).public()
    payload["matched_by"] = {"qid": qid} if qid else {
        "category": match_categories(snapshot, category) if category else "random"}
    return payload
