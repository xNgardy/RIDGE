#!/usr/bin/env python3
"""Summarize X-Plane Data.txt frame-rate output."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


FPS_HEADER_PATTERNS = (
    re.compile(r"f-?act", re.IGNORECASE),
    re.compile(r"frame.*rate", re.IGNORECASE),
    re.compile(r"\bfps\b", re.IGNORECASE),
)


def split_data_line(line: str) -> list[str]:
    return [part.strip() for part in line.strip().split("|") if part.strip()]


def parse_rows(path: Path) -> tuple[list[str], list[list[float]]]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
    if not lines:
        raise SystemExit(f"No rows found in {path}")

    headers = split_data_line(lines[0])
    rows: list[list[float]] = []
    for line in lines[1:]:
        parts = split_data_line(line)
        if len(parts) != len(headers):
            continue
        try:
            rows.append([float(part) for part in parts])
        except ValueError:
            continue

    if not rows:
        raise SystemExit(f"No numeric rows found in {path}")
    return headers, rows


def find_fps_column(headers: list[str]) -> int:
    for idx, header in enumerate(headers):
        normalized = header.replace("_", " ").strip()
        if any(pattern.search(normalized) for pattern in FPS_HEADER_PATTERNS):
            return idx
    raise SystemExit(
        "Could not find an FPS column. In X-Plane, enable Settings > Data Output > Frame rate > Disk File."
    )


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * pct)))
    return ordered[index]


def summarize(path: Path) -> dict[str, float | int | str]:
    headers, rows = parse_rows(path)
    fps_col = find_fps_column(headers)
    fps_values = [row[fps_col] for row in rows if row[fps_col] > 0]
    if not fps_values:
        raise SystemExit("FPS column was found, but it did not contain positive numeric values.")

    return {
        "source": str(path),
        "fps_column": headers[fps_col],
        "sample_count": len(fps_values),
        "average_fps": sum(fps_values) / len(fps_values),
        "one_percent_low_fps": percentile(fps_values, 0.01),
        "minimum_fps": min(fps_values),
        "maximum_fps": max(fps_values),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_txt", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    summary = summarize(args.data_txt)
    print(json.dumps(summary, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["metric", "value"])
            for key, value in summary.items():
                writer.writerow([key, value])


if __name__ == "__main__":
    main()
