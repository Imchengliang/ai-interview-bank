#!/usr/bin/env python3
"""End-to-end smoke test. READ-ONLY with respect to the question bank.

Checks: config, bank parsing/verify, graph, preview gating, dry-run staging,
MCP stdio handshake, and that the bank file is byte-for-byte untouched.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import bank, config, graph, pipeline, sources  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    results.append((label, bool(condition), detail))


def main() -> int:
    cfg, used = config.load_config()
    before = (cfg.bank_path.stat().st_mtime_ns, cfg.bank_path.stat().st_size)
    check("config loads", cfg.write_policy == "preview-confirm", str(used))

    snapshot = bank.parse_bank(cfg.bank_path)
    verification = bank.verify(snapshot)
    check("bank parses", verification["total"] > 0, f"total={verification['total']}")
    check("bank integrity", verification["ok"], str(verification["missing_fields"][:3]))
    check("fenced example ignored",
          all(not q.topic.startswith("原题题干") for q in snapshot.questions))

    built = graph.build(snapshot, cfg)
    check("graph has nodes/edges", len(built.nodes) > 0 and len(built.edges) > 0,
          f"nodes={len(built.nodes)} edges={len(built.edges)}")
    saved = graph.save(cfg, built, snapshot)
    check("graph artefacts written", all(Path(saved[k]).exists()
                                        for k in ("json", "mermaid", "gaps")))
    check("related edges come from 关联",
          any(e["kind"] == "RELATED" for e in built.edges))
    if snapshot.questions:
        neighbor = built.neighbors(snapshot.questions[0].id)
        check("neighbors works", neighbor["question"] == snapshot.questions[0].id)

    status = pipeline.status(cfg)
    check("status reports modes", status["enabled_modes"] == ["m0_manual_link"],
          str(status["enabled_modes"]))

    fake = sources.Candidate(
        source_id="smoke-test-candidate", mode="m0_manual_link",
        url="local://smoke", title="smoke", text="测试正文", status="ok")
    preview = pipeline.preview(cfg, [fake])
    check("preview returns id", "preview_id" in preview, preview.get("preview_id", ""))
    check("preview is read-only", preview["write_policy"] == "preview-confirm")

    refused = pipeline.stage(cfg, preview["preview_id"], [
        {"category": "Agent 与工具调用", "topic": "smoke", "relation": "无"}],
        confirm=False)
    check("stage gated without --confirm", refused.get("staged") is False)

    dry = bank.stage_questions(snapshot, [
        bank.NewQuestion(category="Agent 与工具调用", topic="smoke")], dry_run=True)
    check("dry-run staging does not change text", dry["text"] == snapshot.text)

    server = subprocess.Popen(
        [sys.executable, str(ROOT / "mcp_server.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=str(ROOT))
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "bank_status", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "resources/list", "params": {}},
    ]
    payload = "\n".join(json.dumps(m, ensure_ascii=False) for m in messages) + "\n"
    stdout, _ = server.communicate(payload, timeout=30)
    replies = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    check("MCP replies to all requests", len(replies) == 4, f"got {len(replies)}")
    if len(replies) >= 2:
        check("MCP tools/list is read-only",
              all("write" not in t["name"] and "stage" not in t["name"]
                  for t in replies[1]["result"]["tools"]))
    if len(replies) >= 3:
        check("MCP bank_status works",
              "questions" in replies[2]["result"]["content"][0]["text"])
    if len(replies) >= 4:
        check("MCP resources empty (dsh)", replies[3]["result"] == {"resources": []})

    # Confirmed staging on a throwaway copy of the bank (never the real one).
    tmpdir = Path(tempfile.mkdtemp(prefix="aibank-e2e-"))
    tmpbank = tmpdir / "bank.md"
    shutil.copyfile(cfg.bank_path, tmpbank)
    original = bank.parse_bank(tmpbank)
    local = config.Config(bank_path=tmpbank, write_policy="preview-confirm",
                          state_dir=tmpdir / "state", graph_dir=tmpdir / "graph")
    cand = sources.Candidate(source_id="smoke-e2e", mode="m0_manual_link",
                             url="local://e2e", text="测试", status="ok")
    preview_id = pipeline.preview(local, [cand])["preview_id"]
    staged = pipeline.stage(local, preview_id, [
        {"category": "LLM 基础与原理", "topic": "端到端测试题",
         "relation": "无"}], confirm=True)
    check("confirmed staging succeeds", staged.get("staged") is True,
          str(staged.get("reason", "")))
    after_text = tmpbank.read_text(encoding="utf-8")
    after_snapshot = bank.parse_bank(tmpbank)
    check("staging adds exactly one question",
          len(after_snapshot.questions) == len(original.questions) + 1)
    check("staging preserves every original block",
          all(q.raw in after_text for q in original.questions))
    check("staging removes empty-section placeholder",
          "_暂无题目_" not in after_text.split("### 1. LLM 基础与原理")[1].split("### 2.")[0])
    check("staged question stays 待分析",
          bank.verify(after_snapshot)["pending"] == ["Q186"])
    check("staging marks source cursor",
          "smoke-e2e" in sources.load_cursor(local)["processed"])
    shutil.rmtree(tmpdir, ignore_errors=True)

    after = (cfg.bank_path.stat().st_mtime_ns, cfg.bank_path.stat().st_size)
    check("question bank untouched", before == after)

    for label, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
