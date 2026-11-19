"""Summarize a verification network JSON for quality review."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def summarize(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    summary = data.get("summary") or {}

    print(f"=== {path.name} ===")
    print(
        f"nodes={len(nodes)} edges={len(edges)} "
        f"documents={len(data.get('documents') or [])} "
        f"verified={summary.get('items_with_verified_evidence')} "
        f"unverified={summary.get('items_with_unverified_evidence')} "
        f"no_evidence={summary.get('items_without_evidence')}"
    )
    print("types:", dict(Counter(node.get("type") for node in nodes).most_common()))
    print("edge types:", dict(Counter(edge.get("type") for edge in edges).most_common()))

    print("\n-- nodes --")
    for node in sorted(nodes, key=lambda n: -len(n.get("evidence") or [])):
        ev = node.get("evidence") or []
        verified = sum(1 for e in ev if e.get("quote_verified"))
        print(
            f"{node.get('type','?'):<14} {node.get('name','?')[:38]:<38} "
            f"ev={len(ev)}/{verified} deg={node.get('degree',0)}"
        )
        if ev:
            first = ev[0]
            print(
                f"    p{first.get('page')}: {str(first.get('quote',''))[:110]}"
            )

    print("\n-- edges --")
    for edge in sorted(edges, key=lambda e: -len(e.get("evidence") or [])):
        ev = edge.get("evidence") or []
        verified = sum(1 for e in ev if e.get("quote_verified"))
        print(
            f"{edge.get('type','?'):<14} "
            f"{str(edge.get('source_name','?'))[:26]:<26} -> "
            f"{str(edge.get('target_name','?'))[:26]:<26} ev={len(ev)}/{verified}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("networks", nargs="+", help="Network JSON files")
    args = parser.parse_args()
    for raw in args.networks:
        summarize(Path(raw))
        print()


if __name__ == "__main__":
    main()
