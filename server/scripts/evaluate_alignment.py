"""Report alignment accuracy for manually checked timestamp labels.

Example:
    MARGINALIA_COURSES=/path/to/courses uv run python scripts/evaluate_alignment.py \
        operating-system checked.json

``checked.json`` is a JSON list of ``{"video", "time", "deck", "slide"}``.
It intentionally contains only labels, never course files or video frames.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from marginalia.store import Course


def at_time(segments: list[dict], video: str, timestamp: float) -> dict | None:
    return next((segment for segment in segments if segment["video"] == video and segment["start"] <= timestamp < segment["end"]), None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("course")
    parser.add_argument("labels")
    args = parser.parse_args()
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    segments = Course(args.course).alignment()["segments"]
    correct = 0
    for label in labels:
        actual = at_time(segments, label["video"], label["time"])
        expected = (label.get("deck"), label.get("slide"))
        found = (actual.get("deck"), actual.get("slide")) if actual else (None, None)
        correct += found == expected
        print(f"{label['video']}@{label['time']}: {found} {'OK' if found == expected else 'FAIL'}")
    print(f"accuracy: {correct}/{len(labels)} ({correct / len(labels):.1%})")


if __name__ == "__main__":
    main()
