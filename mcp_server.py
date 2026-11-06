#!/usr/bin/env python3
"""Minimal read-only MCP server over stdio (newline-delimited JSON-RPC 2.0).

Zero dependencies: the local Python has no mcp/fastmcp SDK. Only read tools are
exposed -- writing goes through the local CLI/Skill, which also avoids Codex's
known behavior of auto-declining third-party MCP write calls.

Note: DeepSeek Harness does not enable MCP servers by default and only bridges
Tools (no resources/prompts); this server therefore returns empty lists for
resources/list and prompts/list.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import bank, config, graph, pipeline, sources  # noqa: E402

SERVER_INFO = {"name": "ai-interview-bank", "version": "0.1.0"}

TOOLS = [
    {
        "name": "bank_status",
        "description": "题库统计、下一个可用编号、待分析题、空白类别与已启用模式",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_questions",
        "description": "列出现有题目（供语义去重）；可按类别或状态过滤",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "status": {"type": "string", "enum": ["待分析", "已分析"]},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "search_questions",
        "description": "在题干/考什么/关联/参考答案中检索关键词",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer", "default": 20}},
            "required": ["query"]},
    },
    {
        "name": "graph_summary",
        "description": "知识图谱薄弱点：类别分布、空类别、孤立题、高频实体",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "graph_neighbors",
        "description": "某道题的一跳关联题与命中的技术实体",
        "inputSchema": {"type": "object", "properties": {
            "qid": {"type": "string"}}, "required": ["qid"]},
    },
    {
        "name": "preview_note",
        "description": "只读：拉取一个小红书帖子，返回正文/图片路径与预览号，不写题库",
        "inputSchema": {"type": "object", "properties": {
            "url": {"type": "string"}, "no_images": {"type": "boolean", "default": False}},
            "required": ["url"]},
    },
]


def _text(payload) -> dict:
    return {"content": [{"type": "text",
                         "text": json.dumps(payload, ensure_ascii=False, indent=2)}]}


def call_tool(name: str, args: dict) -> dict:
    cfg, _ = config.load_config()
    if name == "bank_status":
        return pipeline.status(cfg)
    if name == "list_questions":
        snapshot = bank.parse_bank(cfg.bank_path)
        rows = [{"id": q.id, "category": q.category, "status": q.status,
                 "topic": q.topic} for q in snapshot.questions]
        if args.get("category"):
            rows = [r for r in rows if args["category"] in r["category"]]
        if args.get("status"):
            rows = [r for r in rows if r["status"] == args["status"]]
        return {"total": len(rows), "next_id": snapshot.next_id,
                "questions": rows[: int(args.get("limit", 50))]}
    if name == "search_questions":
        snapshot = bank.parse_bank(cfg.bank_path)
        return {"query": args["query"],
                "hits": bank.search(snapshot, args["query"], int(args.get("limit", 20)))}
    if name == "graph_summary":
        path = cfg.graph_dir / "gaps.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
            "error": "图谱未生成，请运行 cli.py graph --refresh"}
    if name == "graph_neighbors":
        return graph.load(cfg).neighbors(str(args["qid"]).upper())
    if name == "preview_note":
        candidate = sources.fetch_note(args["url"], cfg,
                                       download_images=not args.get("no_images", False))
        result = pipeline.preview(cfg, [candidate])
        result["candidate_file"] = str(
            cfg.state_dir / "candidates" / f"{candidate.source_id}.json")
        return result
    raise ValueError(f"unknown tool: {name}")


def handle(message: dict) -> dict:
    request_id = message.get("id")
    method = message.get("method", "")
    params = message.get("params", {}) or {}

    def ok(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def fail(code: int, text: str) -> dict:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": code, "message": text}}

    if method == "initialize":
        return ok({
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        try:
            return ok(_text(call_tool(params.get("name", ""),
                                      params.get("arguments", {}) or {})))
        except Exception as exc:  # surface a readable MCP error
            return ok({**_text({"error": str(exc)}), "isError": True})
    if method in ("resources/list", "prompts/list"):
        return ok({method.split("/")[0]: []})
    return fail(-32601, f"Method not found: {method}")


def serve() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in message:  # notification, no response
            continue
        sys.stdout.write(json.dumps(handle(message), ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    serve()
