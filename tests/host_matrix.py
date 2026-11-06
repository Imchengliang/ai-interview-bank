#!/usr/bin/env python3
"""Cross-host verification matrix for the AI interview bank plugin.

    python3 tests/host_matrix.py [plugin_root]

Read-only. It never writes the question bank, never sends model requests, and
never changes any host's global config. Optional checks are SKIPped when the
host CLI or an installed plugin is absent.

Verified on 2026-11-06 with:
  claude 2.1.234 / codex 0.164.0 / dsh 0.1.5-rc.1 / WorkBuddy skill toolchain
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
RESULTS: list[tuple[str, str, str]] = []


def run(cmd: list[str], timeout: int = 60, cwd: Path | None = None):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return None, "", "command not found"
    except subprocess.TimeoutExpired:
        return None, "", "timeout"


def record(host: str, check: str, ok: bool | None, detail: str) -> None:
    state = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
    RESULTS.append((host, check, f"{state}  {detail}"))


def has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def main() -> int:
    # ---- local core -------------------------------------------------------
    rc, out, err = run([sys.executable, str(ROOT / "cli.py"), "verify"])
    try:
        data = json.loads(out)
        record("local", "cli.py verify", data.get("ok") is True,
               f"total={data.get('total')} next={data.get('next_id')} pending={data.get('pending')}")
    except Exception:
        record("local", "cli.py verify", False, (err or out)[:150])

    rc, out, err = run([sys.executable, str(ROOT / "tests" / "smoke_test.py")], timeout=120)
    tail = [l for l in out.splitlines() if "PASS" in l or "passed" in l or "FAIL" in l]
    record("local", "smoke_test.py (incl. MCP handshake)", rc == 0,
           (tail[-1] if tail else (err or "no output")[:150]))

    graph = ROOT / "graph" / "knowledge_graph.json"
    gaps = ROOT / "graph" / "gaps.json"
    record("local", "graph artefacts", graph.exists() and gaps.exists(),
           f"knowledge_graph.json={graph.exists()} gaps.json={gaps.exists()}")

    # ---- WorkBuddy --------------------------------------------------------
    wb = Path("/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/"
              "resources/plugins/workbuddy-builtin/skills/skill-creator/scripts/package_skill.py")
    if wb.exists():
        rc, out, err = run([sys.executable, str(wb), str(ROOT), "/tmp/aibank-host-matrix-dist"], timeout=90)
        record("WorkBuddy", "official package_skill.py", rc == 0,
               "packaging passed" if rc == 0 else (err or out)[-150:])
    else:
        record("WorkBuddy", "official package_skill.py", None, "WorkBuddy skill-creator not installed")

    # ---- Claude Code ------------------------------------------------------
    if not has("claude"):
        record("Claude Code", "all checks", None, "claude CLI not found")
    else:
        rc, out, err = run(["claude", "plugin", "validate", "--strict", str(ROOT)])
        record("Claude Code", "plugin validate --strict", rc == 0,
               "manifest valid" if rc == 0 else (out + err)[-180:])

        rc, out, err = run(["claude", "plugin", "list"])
        installed = "ai-interview-bank@" in out
        if installed:
            rc2, out2, err2 = run(["claude", "plugin", "details", "ai-interview-bank"])
            record("Claude Code", "plugin details (Skill + MCP)", rc2 == 0,
                   "1 Skill / 1 MCP" if "MCP servers (1)" in out2 else (out2 + err2)[-150:])

            rc3, out3, err3 = run(["claude", "mcp", "list"], timeout=90)
            record("Claude Code", "MCP health", "Connected" in out3 and "Failed" not in out3,
                   "Connected" if "Connected" in out3 else (out3 + err3)[-180:])
        else:
            record("Claude Code", "installed plugin / MCP health", None,
                   "plugin not installed; run marketplace add + plugin install")

    # ---- Codex ------------------------------------------------------------
    if not has("codex"):
        record("Codex", "all checks", None, "codex CLI not found")
    else:
        rc, out, err = run(["codex", "mcp", "get", "ai-interview-bank", "--json"])
        try:
            cfg = json.loads(out)
            argv = cfg.get("transport", {}).get("args", [])
            launcher = " ".join(argv)
            ok = "mcp_server.py" in launcher and "plugins/cache" in launcher
            record("Codex", "MCP launcher is host-independent", ok,
                   "fallback launcher present" if ok else "uses a host-specific variable only")
        except Exception:
            record("Codex", "MCP launcher is host-independent", None,
                   "plugin MCP not registered; run marketplace add + plugin add")

        rc, out, err = run(["codex", "plugin", "list", "--json"])
        try:
            installed = any("ai-interview-bank" in json.dumps(x) and x.get("installed")
                            for x in json.loads(out).get("installed", []))
            record("Codex", "plugin installed", installed,
                   "installed=true" if installed else "not installed")
        except Exception:
            record("Codex", "plugin installed", None, "could not parse plugin list")

    # ---- DeepSeek Harness -------------------------------------------------
    if not has("dsh"):
        record("dsh", "all checks", None, "dsh CLI not found")
    else:
        patch = ROOT / "agents" / "deepseek-harness" / "cordis.patch.yml"
        rc, out, err = run(["dsh", "--profile", "web", "--patch", str(patch), "--dump-config"])
        record("dsh", "bundle patch composes", rc == 0 and "id: ai-interview-bank" in out,
               "bundle entry injected" if "id: ai-interview-bank" in out else (err or "not injected")[:150])

        node = shutil.which("node")
        test = ROOT / "tests" / "dsh_adapter_test.mjs"
        if node and test.exists():
            rc, out, err = run([node, str(test), str(ROOT)], timeout=90)
            record("dsh", "adapter runtime (real dsh-tools)", rc == 0,
                   out.strip()[:170] if rc == 0 else (err or out)[-170:])
        else:
            record("dsh", "adapter runtime (real dsh-tools)", None, "node or test file missing")

    # ---- report -----------------------------------------------------------
    print("\n=== Host verification matrix ===")
    width = max(len(c) for _, c, _ in RESULTS)
    for host, check, result in RESULTS:
        print(f"  {host:<14} {check:<{width}}  {result}")
    fails = [r for r in RESULTS if r[2].startswith("FAIL")]
    skips = [r for r in RESULTS if r[2].startswith("SKIP")]
    print(f"\n  PASS={len(RESULTS) - len(fails) - len(skips)}  FAIL={len(fails)}  SKIP={len(skips)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
