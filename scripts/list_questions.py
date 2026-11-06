#!/usr/bin/env python3
"""List existing questions in the AI interview question bank for dedup checks.

Usage:
    python3 list_questions.py [--path /abs/path/to/ai_question.md]

Prints one line per recorded question (id | category | status | topic),
the next usable id, and the sections that are still empty. The fenced
example block inside the bank file is ignored on purpose.
"""

import argparse
import re
from pathlib import Path

DEFAULT_PATH = Path.home() / "Documents" / "interview" / "ai_question.md"

HEADER_RE = re.compile(r"^####\s+Q(\d+)\s*·\s*(.*?)\s*·\s*状态：\s*(\S+)")
TOPIC_RE = re.compile(r"^\*\*题目\*\*：\s*(.*)$")
SECTION_RE = re.compile(r"^###\s+(\d+)\.\s+(.*)$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()

    if not args.path.exists():
        print(f"BANK_MISSING: {args.path}")
        print("NEXT_ID: Q001")
        return 0

    lines = args.path.read_text(encoding="utf-8").splitlines()
    in_code = False
    rows = []
    current_section = None
    section_counts = {}
    empty_sections = []
    max_id = 0
    current = None

    for line in lines:
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue

        section = SECTION_RE.match(line)
        if section:
            current_section = section.group(1)
            section_counts.setdefault(current_section, 0)
            continue

        header = HEADER_RE.match(line)
        if header:
            number = int(header.group(1))
            max_id = max(max_id, number)
            current = {
                "id": f"Q{number:03d}",
                "category": header.group(2).strip(),
                "status": header.group(3).strip(),
                "topic": "(no topic line)",
            }
            rows.append(current)
            if current_section:
                section_counts[current_section] = section_counts.get(current_section, 0) + 1
            continue

        if current is not None:
            topic = TOPIC_RE.match(line)
            if topic:
                current["topic"] = topic.group(1).strip()

        if "_暂无题目_" in line and current_section:
            empty_sections.append(current_section)

    print(f"BANK: {args.path}")
    print(f"TOTAL: {len(rows)}")
    print(f"NEXT_ID: Q{max_id + 1:03d}")
    print(f"EMPTY_SECTIONS: {', '.join(empty_sections) if empty_sections else '(none)'}")
    print("--- QUESTIONS ---")
    for row in rows:
        topic = row["topic"]
        if len(topic) > 90:
            topic = topic[:90] + "…"
        print(f"{row['id']} | {row['category']} | {row['status']} | {topic}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
