"""Measure local FastEmbed throughput with isolated thread configurations."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastembed import TextEmbedding


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = PROJECT_ROOT / "data" / "corpus.jsonl"
MODEL_NAME = "BAAI/bge-small-en-v1.5"
CACHE_DIR = PROJECT_ROOT / ".model_cache"
DIMENSIONS = 384


def _read_sample(sample_size: int) -> list[str]:
    texts = []
    with CORPUS_PATH.open(encoding="utf-8") as corpus:
        for line_number, line in enumerate(corpus, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                raise ValueError(f"invalid corpus JSON at line {line_number}") from None
            text = record.get("text") if isinstance(record, dict) else None
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"corpus row {line_number} has no text")
            texts.append(text)
            if len(texts) == sample_size:
                break
    if len(texts) != sample_size:
        raise ValueError(f"requested {sample_size} paragraphs, found {len(texts)}")
    return texts


def _measure_worker(threads: int, sample_size: int, repeats: int) -> dict[str, Any]:
    texts = _read_sample(sample_size)
    started = time.perf_counter()
    model = TextEmbedding(
        model_name=MODEL_NAME,
        cache_dir=str(CACHE_DIR),
        threads=threads,
        local_files_only=True,
    )
    initialization_seconds = time.perf_counter() - started

    warmup_started = time.perf_counter()
    warmup = list(model.passage_embed(texts[:1]))
    warmup_seconds = time.perf_counter() - warmup_started
    if len(warmup) != 1 or len(warmup[0]) != DIMENSIONS:
        raise RuntimeError("warmup embedding did not have 384 dimensions")

    run_seconds = []
    for _ in range(repeats):
        started = time.perf_counter()
        vectors = list(model.passage_embed(texts))
        elapsed = time.perf_counter() - started
        if len(vectors) != sample_size:
            raise RuntimeError("embedding returned an unexpected vector count")
        if any(
            len(vector) != DIMENSIONS
            or not all(math.isfinite(float(value)) for value in vector)
            for vector in vectors
        ):
            raise RuntimeError("embedding returned an invalid 384-dimensional vector")
        run_seconds.append(elapsed)

    median_seconds = statistics.median(run_seconds)
    return {
        "threads": threads,
        "model": MODEL_NAME,
        "dimensions": DIMENSIONS,
        "sample_size": sample_size,
        "repeats": repeats,
        "model_initialization_seconds": round(initialization_seconds, 4),
        "warmup_seconds": round(warmup_seconds, 4),
        "repeat_seconds": [round(value, 4) for value in run_seconds],
        "median_seconds": round(median_seconds, 4),
        "median_paragraphs_per_second": round(sample_size / median_seconds, 3),
        "cache_mode": "project-local, offline-only",
    }


def _run_isolated(threads: int, sample_size: int, repeats: int) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker-threads",
            str(threads),
            "--sample-size",
            str(sample_size),
            "--repeats",
            str(repeats),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    output_line = result.stdout.strip().splitlines()[-1]
    return json.loads(output_line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--sample-size", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--worker-threads", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.sample_size < 1 or args.repeats < 1:
        parser.error("sample-size and repeats must be positive")
    if args.worker_threads is not None:
        print(json.dumps(_measure_worker(args.worker_threads, args.sample_size, args.repeats)))
        return 0
    if any(threads < 1 for threads in args.threads):
        parser.error("thread counts must be positive")
    output = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "configurations": [
            _run_isolated(threads, args.sample_size, args.repeats)
            for threads in args.threads
        ],
    }
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
