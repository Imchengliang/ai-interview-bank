#!/usr/bin/env python3
"""CLI for the portable AI interview question bank plugin.

All output is JSON so any agent can parse it. Writing to the bank only happens
in `stage --confirm`; everything else is read-only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import bank, config, graph, pipeline, sources  # noqa: E402


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_init(args) -> None:
    root = config.PACKAGE_ROOT
    target = root / "config.json"
    if not target.exists():
        shutil.copyfile(config.EXAMPLE_CONFIG, target)
    cfg, used = config.load_config()
    config.ensure_dirs(cfg)
    if not cfg.cursor_path.exists():
        cfg.cursor_path.write_text(
            json.dumps({"version": 1, "processed": {}}, indent=2) + "\n",
            encoding="utf-8")
    result = pipeline.finalize(cfg)
    emit({"config_path": str(used), "config": cfg.to_dict(),
          "bank_exists": cfg.bank_path.exists(), "finalize": result})


def cmd_status(args) -> None:
    cfg, used = config.load_config(args.config)
    emit({"config_path": str(used), **pipeline.status(cfg)})


def cmd_verify(args) -> None:
    cfg, _ = config.load_config(args.config)
    snapshot = bank.parse_bank(cfg.bank_path)
    emit({"bank": str(cfg.bank_path), **bank.verify(snapshot)})


def cmd_preview(args) -> None:
    cfg, _ = config.load_config(args.config)
    config.ensure_dirs(cfg)
    candidates = []
    if args.url:
        candidates.append(sources.fetch_note(
            args.url, cfg, download_images=not args.no_images))
    if args.text_file:
        path = Path(args.text_file).expanduser()
        body = path.read_text(encoding="utf-8")
        candidates.append(sources.Candidate(
            source_id="local-" + path.stem, mode="m0_manual_link",
            url=str(path), title=path.stem, text=body,
            status="ok", fetched_at=args.text_file))
    if not candidates:
        emit({"error": "需要 --url 或 --text-file"})
        return
    result = pipeline.preview(cfg, candidates)
    result["candidate_files"] = [
        str(cfg.state_dir / "candidates" / f"{c['source_id']}.json")
        for c in result["candidates"]]
    emit(result)


def cmd_stage(args) -> None:
    cfg, _ = config.load_config(args.config)
    items = json.loads(Path(args.items).expanduser().read_text(encoding="utf-8"))
    emit(pipeline.stage(cfg, args.preview, items, confirm=args.confirm))


def cmd_finalize(args) -> None:
    cfg, _ = config.load_config(args.config)
    emit(pipeline.finalize(cfg))


def cmd_graph(args) -> None:
    cfg, _ = config.load_config(args.config)
    if args.refresh:
        snapshot = bank.parse_bank(cfg.bank_path)
        emit(graph.save(cfg, graph.build(snapshot, cfg), snapshot))
        return
    fmt = args.format
    paths = {"json": cfg.graph_dir / "knowledge_graph.json",
             "mermaid": cfg.graph_dir / "knowledge_graph.mmd",
             "gaps": cfg.graph_dir / "gaps.json",
             "summary": cfg.graph_dir / "gaps.json"}
    path = paths[fmt]
    if not path.exists():
        emit({"error": "图谱未生成，请先 --refresh"})
        return
    if fmt == "json":
        emit(json.loads(path.read_text(encoding="utf-8")))
    elif fmt == "gaps" or fmt == "summary":
        emit(json.loads(path.read_text(encoding="utf-8")))
    else:
        print(path.read_text(encoding="utf-8"), end="")


def cmd_search(args) -> None:
    cfg, _ = config.load_config(args.config)
    snapshot = bank.parse_bank(cfg.bank_path)
    emit({"query": args.query, "hits": bank.search(snapshot, args.query, args.limit)})


def cmd_neighbors(args) -> None:
    cfg, _ = config.load_config(args.config)
    emit(graph.load(cfg).neighbors(args.qid.upper()))


def cmd_mcp(args) -> None:
    from mcp_server import serve
    serve()


def main() -> int:
    parser = argparse.ArgumentParser(prog="ai-interview-bank")
    parser.add_argument("--config", type=Path, default=None,
                        help="config.json 路径（默认包内 config.json / config.example.json）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="生成 config.json、游标并从题库生成图谱").set_defaults(func=cmd_init)
    sub.add_parser("status", help="题库与插件状态").set_defaults(func=cmd_status)
    sub.add_parser("verify", help="题库结构与编号完整性校验").set_defaults(func=cmd_verify)

    preview = sub.add_parser("preview", help="M0：拉取一个帖子并生成只读预览")
    preview.add_argument("--url", default="")
    preview.add_argument("--text-file", default="")
    preview.add_argument("--no-images", action="store_true")
    preview.set_defaults(func=cmd_preview)

    stage = sub.add_parser("stage", help="确认后批量写入题头（状态待分析）")
    stage.add_argument("--preview", required=True)
    stage.add_argument("--items", required=True, help="JSON 文件：[{category,topic,relation}]")
    stage.add_argument("--confirm", action="store_true")
    stage.set_defaults(func=cmd_stage)

    sub.add_parser("finalize", help="Step 5 机械收尾：校验 + 重算图谱").set_defaults(func=cmd_finalize)

    gp = sub.add_parser("graph", help="知识图谱导出")
    gp.add_argument("--refresh", action="store_true")
    gp.add_argument("--format", choices=["json", "mermaid", "gaps", "summary"],
                    default="summary")
    gp.set_defaults(func=cmd_graph)

    sp = sub.add_parser("search", help="题库全文检索")
    sp.add_argument("--query", required=True)
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_search)

    nb = sub.add_parser("neighbors", help="某题的一跳关联与实体")
    nb.add_argument("--qid", required=True)
    nb.set_defaults(func=cmd_neighbors)

    sub.add_parser("mcp", help="启动只读 MCP stdio server").set_defaults(func=cmd_mcp)

    args = parser.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError) as exc:
        emit({"error": str(exc)})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
