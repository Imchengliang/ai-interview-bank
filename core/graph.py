"""Build a knowledge graph from fields that already exist in ai_question.md.

No LLM inference and no hand-written concept list: nodes/edges are deterministic.
Question <-> Question edges come straight from the **关联** field (which already
carries a one-line description of the difference). Question <-> Entity and
Question <-> Angle use a configurable term list and a small keyword heuristic.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .bank import BankSnapshot, Question
from .config import Config, ensure_dirs

ANGLE_RULES = [
    ("排错", ("怎么排查", "怎么定位", "卡死", "失败", "出错", "跑飞", "瓶颈", "归因", "差怎么")),
    ("选型", ("怎么选", "如何选", "取舍", "对比", "区别", "差异", "还是", "选型")),
    ("评测", ("怎么评估", "如何衡量", "指标", "评测", "基线", "效果提升", "判断没丢")),
    ("实现", ("怎么实现", "怎么设计", "如何落地", "手写", "手撕", "怎么构建", "怎么搭")),
    ("原理", ("是什么", "为什么", "核心", "原理", "如何理解", "怎么看")),
]


@dataclass
class Graph:
    nodes: dict = field(default_factory=dict)
    edges: list = field(default_factory=list)

    def node(self, nid: str, kind: str, label: str, **extra) -> None:
        self.nodes[nid] = {"id": nid, "kind": kind, "label": label, **extra}

    def edge(self, source: str, target: str, kind: str, note: str = "") -> None:
        self.edges.append({"source": source, "target": target,
                           "kind": kind, "note": note})

    def neighbors(self, qid: str) -> dict:
        nid = f"q:{qid}"
        related = []
        for e in self.edges:
            if e["kind"] != "RELATED":
                continue
            if e["source"] == nid:
                related.append({"id": e["target"].split(":", 1)[1],
                                "direction": "outgoing", "note": e["note"]})
            elif e["target"] == nid:
                related.append({"id": e["source"].split(":", 1)[1],
                                "direction": "incoming", "note": e["note"]})
        entities = [e["target"].split(":", 1)[1] for e in self.edges
                    if e["kind"] == "MENTIONS" and e["source"] == nid]
        return {"question": qid, "related": related, "entities": entities}


def _angle_of(topic: str) -> str:
    for angle, keywords in ANGLE_RULES:
        if any(word in topic for word in keywords):
            return angle
    return "其他"


def _entities_of(question: Question, terms: list[str]) -> list[str]:
    haystack = " ".join([question.topic, question.fields.get("考什么", ""),
                         question.fields.get("参考答案", "")])
    return [term for term in terms if term in haystack]


def build(snapshot: BankSnapshot, cfg: Config) -> Graph:
    graph = Graph()
    for num, name in snapshot.sections.items():
        graph.node(f"cat:{num}", "Category", f"{num}. {name}",
                   question_count=0)
    for angle, _ in ANGLE_RULES:
        graph.node(f"angle:{angle}", "Angle", angle)
    graph.node("angle:其他", "Angle", "其他")

    for question in snapshot.questions:
        qid = f"q:{question.id}"
        graph.node(qid, "Question", question.topic,
                   category=question.category, status=question.status)
        section = next((num for num, name in snapshot.sections.items()
                        if name == question.category), None)
        if section:
            graph.edge(qid, f"cat:{section}", "IN_CATEGORY")
            cat = graph.nodes[f"cat:{section}"]
            cat["question_count"] = cat.get("question_count", 0) + 1
        graph.edge(qid, f"angle:{_angle_of(question.topic)}", "HAS_ANGLE")
        for term in _entities_of(question, cfg.entity_terms):
            graph.node(f"ent:{term}", "Entity", term)
            graph.edge(qid, f"ent:{term}", "MENTIONS")
        for related in question.relations:
            if related in snapshot.ids:
                # 题库把多个关联写在同一行，无法精确切分到每一对题；
                # 因此保留整段并标明来源题号，避免把上下文误当成两题间的差别。
                graph.edge(qid, f"q:{related}", "RELATED",
                           note=f"来自 {question.id}：{question.fields.get('关联', '')}")
    return graph


def gaps(graph: Graph, snapshot: BankSnapshot) -> dict:
    counts = {n["label"]: n.get("question_count", 0)
              for n in graph.nodes.values() if n["kind"] == "Category"}
    linked = {e["source"] for e in graph.edges if e["kind"] == "RELATED"} | {
        e["target"] for e in graph.edges if e["kind"] == "RELATED"}
    isolated = [q.id for q in snapshot.questions if f"q:{q.id}" not in linked]
    entity_hits: dict[str, int] = {}
    for e in graph.edges:
        if e["kind"] == "MENTIONS":
            key = e["target"].split(":", 1)[1]
            entity_hits[key] = entity_hits.get(key, 0) + 1
    return {
        "total_questions": len(snapshot.questions),
        "category_counts": counts,
        "empty_categories": [label for label, count in counts.items() if count == 0],
        "thin_categories": sorted(counts.items(), key=lambda kv: kv[1])[:3],
        "isolated_questions": isolated,
        "top_entities": sorted(entity_hits.items(), key=lambda kv: -kv[1])[:10],
        "note": "empty_categories / isolated_questions 可驱动 M6 图谱驱动补题（P2）",
    }


def to_jsonld(graph: Graph) -> dict:
    return {
        "@context": {"Question": "https://schema.org/Question",
                     "Category": "https://schema.org/CategoryCode"},
        "generated_by": "ai-interview-bank-plugin/graph.py",
        "nodes": list(graph.nodes.values()),
        "edges": graph.edges,
    }


def to_mermaid(graph: Graph, max_nodes: int = 60) -> str:
    """Compact category-centric view; full graph is in the JSON export."""
    lines = ["graph LR"]
    cats = [n for n in graph.nodes.values() if n["kind"] == "Category"]
    for cat in cats:
        lines.append(f'  {cat["id"]}["{cat["label"]} ({cat.get("question_count", 0)})"]')
    shown = 0
    for q in [n for n in graph.nodes.values() if n["kind"] == "Question"]:
        if shown >= max_nodes:
            break
        label = q["label"].replace('"', "'")[:26]
        lines.append(f'  {q["id"]}["{label}"]')
        for e in graph.edges:
            if e["source"] == q["id"] and e["kind"] == "IN_CATEGORY":
                lines.append(f'  {q["id"]} --> {e["target"]}')
                break
        shown += 1
    return "\n".join(lines) + "\n"


def save(cfg: Config, graph: Graph, snapshot: BankSnapshot) -> dict:
    ensure_dirs(cfg)
    json_path = cfg.graph_dir / "knowledge_graph.json"
    mermaid_path = cfg.graph_dir / "knowledge_graph.mmd"
    gaps_path = cfg.graph_dir / "gaps.json"
    json_path.write_text(json.dumps(to_jsonld(graph), ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    mermaid_path.write_text(to_mermaid(graph), encoding="utf-8")
    report = gaps(graph, snapshot)
    gaps_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    return {"json": str(json_path), "mermaid": str(mermaid_path),
            "gaps": str(gaps_path), "nodes": len(graph.nodes),
            "edges": len(graph.edges), "summary": report}


def load(cfg: Config) -> Graph:
    path = cfg.graph_dir / "knowledge_graph.json"
    if not path.exists():
        raise FileNotFoundError("图谱尚未生成，请先运行 cli.py graph --refresh")
    raw = json.loads(path.read_text(encoding="utf-8"))
    graph = Graph()
    for node in raw["nodes"]:
        graph.nodes[node["id"]] = node
    graph.edges = raw["edges"]
    return graph
