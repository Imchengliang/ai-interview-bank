#!/usr/bin/env python3
"""Download the original images of a Xiaohongshu note (questions are often in images).

Usage:
    python3 fetch_xhs_images.py "<post_url>" [--out /tmp/xhs_imgs]

The desktop page is a JS shell with no note data. With an iPhone UA, the
/explore/<id> page embeds SSR JSON containing `imageList`. CDN formats vary:
older notes use `sns-webpic-qc.xhscdn.com/...!h5_1080jpg`, newer ones may use
`sns-iNN.rednotecdn.com/...?imageView2/2/w/1080/format/jpg`. So first try the
original-suffix pattern, then fall back to the `url` fields inside imageList.
`!style_*` entries are 240x400 thumbnails and must be skipped.
Only stdlib is used.
"""

import argparse
import html
import re
import urllib.parse
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
NOTE_ID_RE = re.compile(r"\b([0-9a-f]{24})\b")
IMG_RE = re.compile(
    r"https?://sns-webpic(?:-qc)?\.xhscdn\.com/[^\s\"'<>\\]+?!h5_1080jpg"
)
LIST_URL_RE = re.compile(r'"url"\s*:\s*"(https?://[^"\\]+)"')
IMG_HOSTS = ("xhscdn.com", "rednotecdn.com")
THUMB_MARKERS = ("!style_", "avatar")


def explore_url(post_url: str) -> str:
    match = NOTE_ID_RE.search(post_url)
    if not match:
        raise SystemExit("ERROR: cannot find a 24-char note id in the URL")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(post_url).query)
    token = query.get("xsec_token", [""])[0]
    url = f"https://www.xiaohongshu.com/explore/{match.group(1)}"
    if token:
        url += f"?xsec_token={token}&xsec_source=pc_share"
    return url


def fetch(url: str, referer: str = "https://www.xiaohongshu.com/") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read()


def image_list_segment(text: str) -> str:
    """Return exactly the JSON array following "imageList" (bracket-counted)."""
    start = text.find('"imageList"')
    if start < 0:
        return ""
    left = text.find("[", start)
    if left < 0:
        return ""
    depth, in_str, escaped = 0, False, False
    for i in range(left, len(text)):
        char = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_str = False
            continue
        if char == '"':
            in_str = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[left : i + 1]
    return ""


def find_image_urls(text: str) -> list[str]:
    candidates = []
    for match in LIST_URL_RE.finditer(image_list_segment(text)):
        url = html.unescape(match.group(1)).replace("\\u0026", "&")
        if any(host in url for host in IMG_HOSTS) and not any(
            marker in url for marker in THUMB_MARKERS
        ):
            candidates.append(url)
    if not candidates:  # last resort for older pages without a usable imageList
        candidates = [m.group(0) for m in IMG_RE.finditer(text)]

    urls, seen = [], set()
    for candidate in candidates:
        url = candidate.replace("http://", "https://")
        file_id = url.split("?", 1)[0].rsplit("/", 1)[-1].split("!")[0]
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)
        urls.append(url)
    return urls


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Xiaohongshu note URL (keep xsec_token if present)")
    parser.add_argument("--out", type=Path, default=Path("/tmp/xhs_imgs"))
    args = parser.parse_args()

    page = explore_url(args.url)
    raw = fetch(page).decode("utf-8", "replace")
    text = html.unescape(raw).replace("\\u002F", "/").replace("\\/", "/")
    urls = find_image_urls(text)

    print(f"PAGE: {page}")
    print(f"IMAGES_FOUND: {len(urls)}")
    if not urls:
        print("HINT: no originals found — the note may need login, or the share token expired.")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    for i, url in enumerate(urls, 1):
        path = args.out / f"img{i:02d}.jpg"
        try:
            data = fetch(url)
            ok = data[:2] == b"\xff\xd8"
            path.write_bytes(data)
            print(f"SAVED {path} ({len(data)} bytes, {'jpeg' if ok else 'NOT JPEG'})")
        except Exception as exc:  # noqa: BLE001 - report per-image failure, keep going
            print(f"FAILED {url}: {exc}")
    print("NEXT: transcribe each image verbatim with the image-reading tool, then merge by number.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
