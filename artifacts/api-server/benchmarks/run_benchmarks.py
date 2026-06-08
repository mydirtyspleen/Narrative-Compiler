"""
ADM-API Benchmark Suite

Measures raw pipeline latency across event batch sizes.
Tests 10, 50, and 100 events with 30 iterations each.
Exports a JSON report to benchmarks/results/benchmark_{timestamp}.json

Usage:
  cd artifacts/api-server
  python -m benchmarks.run_benchmarks

Options:
  --iterations N    Iterations per batch size (default: 30)
  --warmup N        Warmup iterations discarded before measurement (default: 5)
  --sizes 10,50,100 Comma-separated batch sizes to test (default: 1,5,10,50,100)
  --output PATH     Output JSON file path (default: auto-timestamped)
  --quiet           Suppress per-run progress output
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Bootstrap sys.path so we can import adm_api without installation ──────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from adm_api.engine.pipeline import run_pipeline
from adm_api.models.schemas import EventType, GameEvent


# ============================================================================
# Event generation — deterministic test fixtures
# ============================================================================

_EVENT_TYPES = list(EventType)
_ACTOR_POOL  = [
    "faction:Iron_Pact", "faction:Council", "faction:Northern_Legion",
    "player:Alpha", "player:Beta", "region:Tundra", "region:Heartlands",
    "guild:Shadow_Order",
]
_TAG_POOL = [
    "war", "conflict", "crisis", "drought", "siege",
    "skirmish", "reform", "discovery", "collapse",
]


def _make_event(index: int, batch_size: int) -> GameEvent:
    """Generate a deterministic test event. Same index always produces same event."""
    event_type = _EVENT_TYPES[index % len(_EVENT_TYPES)]
    # intensity cycles through a deterministic pattern
    intensity  = round(0.1 + (index % 10) * 0.09, 2)   # 0.10 to 0.91
    actor_idx  = (index * 3) % len(_ACTOR_POOL)
    tag_idx    = (index * 7) % len(_TAG_POOL)

    return GameEvent(
        id        = f"bench-{batch_size}-{index:04d}",
        type      = event_type,
        intensity = intensity,
        actors    = [_ACTOR_POOL[actor_idx]],
        tags      = [_TAG_POOL[tag_idx]],
        payload   = {},
    )


def _make_batch(batch_size: int) -> list[GameEvent]:
    return [_make_event(i, batch_size) for i in range(batch_size)]


# ============================================================================
# Benchmark runner
# ============================================================================

def run_single_benchmark(
    events:     list[GameEvent],
    iterations: int = 30,
    warmup:     int = 5,
    quiet:      bool = False,
) -> dict:
    """
    Run the pipeline `iterations` times against `events`.
    Returns a stats dict: min, max, mean, median, p95, p99, stdev.
    """
    batch_size = len(events)
    all_times: list[float] = []

    # Warmup runs — discarded
    for _ in range(warmup):
        run_pipeline(events, {})

    # Measured runs
    for i in range(iterations):
        t0 = time.perf_counter()
        run_pipeline(events, {})
        elapsed_ms = (time.perf_counter() - t0) * 1000
        all_times.append(elapsed_ms)

        if not quiet and (i + 1) % 10 == 0:
            print(f"  [{batch_size} events] iter {i+1}/{iterations} — last: {elapsed_ms:.3f}ms")

    sorted_times = sorted(all_times)
    p95_idx = max(0, int(len(sorted_times) * 0.95) - 1)
    p99_idx = max(0, int(len(sorted_times) * 0.99) - 1)

    return {
        "batch_size":  batch_size,
        "iterations":  iterations,
        "warmup":      warmup,
        "min_ms":      round(min(all_times), 3),
        "max_ms":      round(max(all_times), 3),
        "mean_ms":     round(statistics.mean(all_times), 3),
        "median_ms":   round(statistics.median(all_times), 3),
        "p95_ms":      round(sorted_times[p95_idx], 3),
        "p99_ms":      round(sorted_times[p99_idx], 3),
        "stdev_ms":    round(statistics.stdev(all_times), 3) if len(all_times) > 1 else 0.0,
        "samples_ms":  [round(t, 3) for t in all_times],
    }


def run_all_benchmarks(
    batch_sizes: list[int] = None,
    iterations:  int       = 30,
    warmup:      int       = 5,
    quiet:       bool      = False,
) -> dict:
    """
    Run benchmarks across all requested batch sizes.

    Note on batch_size vs events_processed:
      event_ranker caps at 10. For batches > 10, the overhead is in
      creating GameEvent objects + ranking sort — the pipeline itself
      always processes at most 10 events. This benchmark measures the
      full path including validation + ranking, not just core pipeline.
    """
    if batch_sizes is None:
        batch_sizes = [1, 5, 10, 50, 100]

    results     = {}
    environment = {
        "python":     sys.version,
        "platform":   sys.platform,
        "cpu_count":  os.cpu_count(),
        "run_at":     datetime.now(timezone.utc).isoformat(),
    }

    print(f"\n{'═'*60}")
    print("  ADM-API Benchmark Suite")
    print(f"{'═'*60}")
    print(f"  Iterations per size : {iterations} (+{warmup} warmup)")
    print(f"  Batch sizes         : {batch_sizes}")
    print(f"{'═'*60}\n")

    for size in batch_sizes:
        if not quiet:
            print(f"▸ Benchmarking {size}-event batch...")
        events = _make_batch(size)
        stats  = run_single_benchmark(events, iterations=iterations, warmup=warmup, quiet=quiet)
        results[str(size)] = stats

        print(
            f"  {size:>4} events │ "
            f"mean={stats['mean_ms']:.3f}ms  "
            f"p95={stats['p95_ms']:.3f}ms  "
            f"p99={stats['p99_ms']:.3f}ms  "
            f"min={stats['min_ms']:.3f}ms  "
            f"max={stats['max_ms']:.3f}ms"
        )
        print()

    # Summary table
    print(f"\n{'─'*60}")
    print(f"  {'Batch':>6}  {'Mean':>8}  {'P95':>8}  {'P99':>8}  {'Stdev':>8}")
    print(f"{'─'*60}")
    for size in batch_sizes:
        s = results[str(size)]
        print(
            f"  {size:>6}  "
            f"{s['mean_ms']:>7.3f}ms  "
            f"{s['p95_ms']:>7.3f}ms  "
            f"{s['p99_ms']:>7.3f}ms  "
            f"{s['stdev_ms']:>7.3f}ms"
        )
    print(f"{'─'*60}\n")
    print("  Note: event_ranker caps at 10 events. For batches >10,")
    print("  the pipeline processes 10 events; overhead is in input handling.")
    print()

    return {
        "environment": environment,
        "results":     results,
    }


# ============================================================================
# Export
# ============================================================================

def export_results(data: dict, output_path: Path | None = None) -> Path:
    """Export benchmark results to JSON."""
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        ts   = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = results_dir / f"benchmark_{ts}.json"

    output_path.write_text(json.dumps(data, indent=2))
    print(f"Results written to: {output_path}")
    return output_path


# ============================================================================
# CLI
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description = "ADM-API pipeline benchmark suite",
        formatter_class = argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--iterations", type=int, default=30,
                        help="Measured iterations per batch size (default: 30)")
    parser.add_argument("--warmup",     type=int, default=5,
                        help="Warmup iterations discarded (default: 5)")
    parser.add_argument("--sizes",      type=str, default="1,5,10,50,100",
                        help="Comma-separated batch sizes (default: 1,5,10,50,100)")
    parser.add_argument("--output",     type=str, default=None,
                        help="Output JSON path (default: auto-timestamped)")
    parser.add_argument("--quiet",      action="store_true",
                        help="Suppress per-run progress output")
    parser.add_argument("--no-export",  action="store_true",
                        help="Run benchmark but skip writing JSON output")

    args        = parser.parse_args()
    batch_sizes = [int(x.strip()) for x in args.sizes.split(",")]

    data = run_all_benchmarks(
        batch_sizes = batch_sizes,
        iterations  = args.iterations,
        warmup      = args.warmup,
        quiet       = args.quiet,
    )

    if not args.no_export:
        out = Path(args.output) if args.output else None
        export_results(data, out)


if __name__ == "__main__":
    main()
