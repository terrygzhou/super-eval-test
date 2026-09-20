"""Drive Phases 3+4 of scripted mode with a hand-authored boundary dataset.

Usage:
  python boundary_run.py --dataset boundary_year.json \
      --target http://localhost:8081 --source /path/to/src \
      --config config.yaml --output ./superApp_output
"""
from __future__ import annotations

import argparse, asyncio, json, time
from pathlib import Path

from src.data_generator import TestDataset, TestRecord
from src.pipeline import Pipeline


def load_dataset(path: Path) -> TestDataset:
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = [TestRecord(**r) for r in raw["records"]]
    return TestDataset(
        records=records,
        metadata={"generator": "hand-authored-boundary", "total_records": len(records)},
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--config", default="")
    ap.add_argument("--output", default="./superApp_output")
    a = ap.parse_args()

    dataset = load_dataset(Path(a.dataset))
    p = Pipeline(
        config_path=a.config or None,
        output_dir=a.output,
        target_url=a.target,
        source_root=a.source,
    )

    start = time.time()
    results = await p.phase3_test(dataset, a.target)
    report = await p.phase4_correlate(results, start)

    passed = sum(1 for r in results if r.status == "passed")
    print(f"\nBoundary run: {passed}/{len(results)} passed")
    for r in results:
        mark = "PASS" if r.status == "passed" else "FAIL"
        print(f"  [{mark}] var{r.variation} {r.form_name} ({r.total_duration_ms}ms)")
    print(f"\nCorrelation report: {p.output_dir}/logs/correlation_report.json")


if __name__ == "__main__":
    asyncio.run(main())
