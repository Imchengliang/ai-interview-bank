"""Source adapters. P0 ships M0 (manual link) only.

A Candidate is the *raw material* for Step 1. Turning it into questions
(transcribing images, extracting question sentences) stays with the LLM.
Nothing here writes to the bank, and the processed-source cursor is internal
metadata only -- it is never written into question entries.
"""

from __future__ import annotations

import hashlib
import html
import importlib.util
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import Config, ensure_dirs, PACKAGE_ROOT

DESC_RE = re.compile(r'"desc"\s*:\s*"((?:[^"\\]|\\.)*)"')
NOTE_ID_RE = re.compile(r"\b([0-9a-f]{24})\b")


@dataclass
class Candidate:
    source_id: str
    mode: str = "m0_manual_link"
    url: str = ""
    title: str = ""
    text: str = ""
    images: list[str] = field(default_factory=list)
    status: str = "ok"          # ok | needs_manual
    hint: str = ""
    fetched_at: str = ""

    def summary(self) -> dict:
        return {
            "source_id": self.source_id, "mode": self.mode, "url": self.url,
            "title": self.title, "text_chars": len(self.text),
            "images": len(self.images), "status": self.status,
            "hint": self.hint, "fetched_at": self.fetched_at,
        }


def _load_image_helper():
    """Reuse the battle-tested fetch_xhs_images.py from the skill snapshot."""
    path = PACKAGE_ROOT / "scripts" / "fetch_xhs_images.py"
    spec = importlib.util.spec_from_file_location("_xhs_images", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _extract_desc(page_text: str) -> str:
    best = ""
    for match in DESC_RE.finditer(page_text):
        try:
            value = json.loads('"' + match.group(1) + '"')
        except (json.JSONDecodeError, ValueError):
            value = match.group(1).replace("\\n", "\n")
        # strip topic tags / zero-width noise
        value = re.sub(r"#[^#\n]*\[话题\]#", "", value)
        value = value.replace("\ufeff", "").replace("\u200b", "").strip()
        if len(value) > len(best):
            best = value
    return best


def fetch_note(url: str, cfg: Config, download_images: bool = True) -> Candidate:
    """M0 adapter: fetch one note via the mobile SSR page.

    Degradation chain: desktop body -> mobile SSR `desc` -> imageList originals
    -> ask the user for text/screenshots. Never guesses question content.
    """
    match = NOTE_ID_RE.search(url)
    source_id = match.group(1) if match else hashlib.sha256(
        url.encode("utf-8")).hexdigest()[:24]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    helper = _load_image_helper()
    try:
        page = helper.explore_url(url)
        raw = helper.fetch(page).decode("utf-8", "replace")
        text = html.unescape(raw).replace("\\u002F", "/").replace("\\/", "/")
        desc = _extract_desc(text)
        image_urls = helper.find_image_urls(text)
        images: list[str] = []
        if download_images and image_urls:
            out = cfg.state_dir / "images" / source_id
            out.mkdir(parents=True, exist_ok=True)
            for i, image_url in enumerate(image_urls, 1):
                try:
                    data = helper.fetch(image_url)
                    target = out / f"img{i:02d}.jpg"
                    target.write_bytes(data)
                    images.append(str(target))
                except Exception as exc:  # keep going on a single bad image
                    images.append(f"FAILED:{image_url}:{exc}")
        status = "ok" if (desc or images) else "needs_manual"
        hint = "" if status == "ok" else (
            "正文与图片都没取到；可能需登录或分享令牌过期，请让用户贴正文或原图。")
        return Candidate(source_id=source_id, url=url, text=desc,
                         images=images, status=status, hint=hint,
                         fetched_at=now)
    except Exception as exc:
        return Candidate(source_id=source_id, url=url, status="needs_manual",
                         hint=f"抓取失败：{exc}；请让用户贴正文或原图。",
                         fetched_at=now)


# --- internal processed-source cursor (NOT written into the bank) ---

def load_cursor(cfg: Config) -> dict:
    ensure_dirs(cfg)
    if not cfg.cursor_path.exists():
        return {"version": 1, "processed": {}}
    return json.loads(cfg.cursor_path.read_text(encoding="utf-8"))


def is_processed(cfg: Config, source_id: str) -> bool:
    return source_id in load_cursor(cfg)["processed"]


def mark_processed(cfg: Config, candidate: Candidate,
                   note: str = "") -> None:
    cursor = load_cursor(cfg)
    cursor["processed"][candidate.source_id] = {
        "url": candidate.url, "mode": candidate.mode,
        "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
    }
    cfg.cursor_path.write_text(
        json.dumps(cursor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --- P1+ adapter registry (P0 intentionally registers nothing else) ---

_ADAPTERS: dict[str, Callable] = {}


def register_adapter(mode: str, fn: Callable) -> None:
    """Hook for M1..M8. Every adapter must return list[Candidate] and MUST NOT
    write to the bank; all writes go through pipeline.stage() after confirmation.
    """
    _ADAPTERS[mode] = fn


def available_adapters() -> list[str]:
    return ["m0_manual_link", *sorted(_ADAPTERS)]
