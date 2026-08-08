"""
Compare SpatialParse accuracy across different LLM models via OpenRouter.

Usage:
    python -m tests.compare_models
    python -m tests.compare_models --models "openai/gpt-4o,google/gemini-2.0-flash-001,anthropic/claude-3.5-sonnet"
"""

import json
import sys
import math
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import backend.config as config
from backend.llm_parser import parse
from backend.geo_engine import execute_steps

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("compare_models")
logger.setLevel(logging.INFO)

# Models to test (OpenRouter format)
DEFAULT_MODELS = [
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "google/gemini-2.0-flash-001",
    "anthropic/claude-sonnet-4",
    "meta-llama/llama-3.1-70b-instruct",
]


def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371 * 2 * math.asin(math.sqrt(a))


def test_model(model_name, dataset):
    """Run dataset through a specific model. Returns list of result dicts."""
    # Switch model
    original_model = config.DEFAULT_MODEL
    config.DEFAULT_MODEL = model_name
    logger.info("=== Testing model: %s ===", model_name)

    results = []
    for i, item in enumerate(dataset):
        idx = item["id"]
        text = item["text"]
        category = item["category"]
        gold_lon = item["gold_lon"]
        gold_lat = item["gold_lat"]
        expected_steps = item.get("expected_steps", [])

        logger.info("  [%d/%d] id=%d: %s", i+1, len(dataset), idx, text[:50])

        result = {
            "id": idx,
            "text": text,
            "category": category,
            "difficulty": item.get("difficulty", "?"),
        }

        # Parse
        t0 = time.time()
        try:
            parsed_steps = parse(text, use_fewshot=True)
            result["parse_time_s"] = round(time.time() - t0, 2)
            result["parse_error"] = None

            # Function match
            pred_funcs = [s.get("function") for s in parsed_steps]
            exp_funcs = [s.get("function") for s in expected_steps]
            result["function_match"] = pred_funcs == exp_funcs
            result["predicted_functions"] = pred_funcs
            result["expected_functions"] = exp_funcs
        except Exception as e:
            logger.error("    Parse FAILED: %s", e)
            result["parse_time_s"] = round(time.time() - t0, 2)
            result["parse_error"] = str(e)
            result["function_match"] = False
            result["distance_error_km"] = None
            results.append(result)
            continue

        # Execute
        t1 = time.time()
        try:
            step_data = execute_steps(parsed_steps)
            result["exec_time_s"] = round(time.time() - t1, 2)

            final_key = max(step_data.keys())
            _, final_centroid = step_data[final_key]
            pred_lon = round(final_centroid[0], 5)
            pred_lat = round(final_centroid[1], 5)

            result["pred_lon"] = pred_lon
            result["pred_lat"] = pred_lat
            result["distance_error_km"] = round(
                haversine(pred_lon, pred_lat, gold_lon, gold_lat), 3)

            logger.info("    OK: err=%.2f km func=%s",
                        result["distance_error_km"], result["function_match"])
        except Exception as e:
            logger.error("    Exec FAILED: %s", e)
            result["exec_time_s"] = round(time.time() - t1, 2)
            result["exec_error"] = str(e)
            result["distance_error_km"] = None

        results.append(result)

    # Restore model
    config.DEFAULT_MODEL = original_model
    return results


def compute_metrics(results):
    """Compute aggregate metrics from results."""
    total = len(results)
    successful = [r for r in results if r.get("distance_error_km") is not None]
    distances = [r["distance_error_km"] for r in successful]

    func_matches = sum(1 for r in results if r.get("function_match"))
    parse_errors = sum(1 for r in results if r.get("parse_error"))
    exec_errors = sum(1 for r in results
                      if r.get("parse_error") is None and r.get("distance_error_km") is None)

    if distances:
        ds = sorted(distances)
        n = len(ds)
        median = ds[n//2] if n % 2 else (ds[n//2-1] + ds[n//2]) / 2
        mean = sum(distances) / n
        acc1 = sum(1 for d in distances if d < 1) / n * 100
        acc5 = sum(1 for d in distances if d < 5) / n * 100
        acc10 = sum(1 for d in distances if d < 10) / n * 100
    else:
        median = mean = acc1 = acc5 = acc10 = 0

    parse_times = [r["parse_time_s"] for r in results if r.get("parse_time_s")]
    avg_parse = round(sum(parse_times) / len(parse_times), 2) if parse_times else 0

    # Per category
    cats = {}
    for r in results:
        cat = r["category"]
        if cat not in cats:
            cats[cat] = {"total": 0, "func_ok": 0, "distances": []}
        cats[cat]["total"] += 1
        if r.get("function_match"):
            cats[cat]["func_ok"] += 1
        if r.get("distance_error_km") is not None:
            cats[cat]["distances"].append(r["distance_error_km"])

    per_cat = {}
    for cat, info in sorted(cats.items()):
        ds = info["distances"]
        per_cat[cat] = {
            "n": info["total"],
            "func_accuracy_%": round(info["func_ok"] / info["total"] * 100, 1),
            "mean_error_km": round(sum(ds)/len(ds), 2) if ds else None,
            "accuracy_5km_%": round(sum(1 for d in ds if d < 5)/len(ds)*100, 1) if ds else 0,
        }

    return {
        "total": total,
        "successful": len(successful),
        "parse_errors": parse_errors,
        "exec_errors": exec_errors,
        "function_accuracy_%": round(func_matches / total * 100, 1),
        "mean_distance_error_km": round(mean, 3),
        "median_distance_error_km": round(median, 3),
        "accuracy_1km_%": round(acc1, 1),
        "accuracy_5km_%": round(acc5, 1),
        "accuracy_10km_%": round(acc10, 1),
        "avg_parse_time_s": avg_parse,
        "per_category": per_cat,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", type=str, default=None,
                        help="Comma-separated list of model IDs")
    parser.add_argument("--dataset", type=str, default="dataset/gold_standard.json")
    parser.add_argument("--output", type=str, default="tests/model_comparison.json")
    args = parser.parse_args()

    models = args.models.split(",") if args.models else DEFAULT_MODELS

    with open(args.dataset, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    logger.info("Dataset: %s (%d examples)", args.dataset, len(dataset))
    logger.info("Models: %s", models)

    comparison = {
        "timestamp": datetime.now().isoformat(),
        "dataset": args.dataset,
        "dataset_size": len(dataset),
        "models": {},
    }

    for model in models:
        t0 = time.time()
        try:
            results = test_model(model, dataset)
            elapsed = round(time.time() - t0, 1)
            metrics = compute_metrics(results)
            metrics["elapsed_s"] = elapsed

            comparison["models"][model] = {
                "metrics": metrics,
                "results": results,
            }

            logger.info("=== %s done: func=%.1f%% median=%.2f km @5km=%.1f%% time=%ds ===",
                        model, metrics["function_accuracy_%"],
                        metrics["median_distance_error_km"],
                        metrics["accuracy_5km_%"], elapsed)
        except Exception as e:
            logger.error("=== %s FAILED: %s ===", model, e)
            comparison["models"][model] = {"error": str(e)}

    # Save full results
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)

    # Print comparison table
    print("\n" + "=" * 100)
    print("  MODEL COMPARISON RESULTS")
    print("=" * 100)
    print(f"  Dataset: {args.dataset} ({len(dataset)} examples)")
    print()
    print(f"  {'Model':<40s} {'Func%':>6s} {'MDE':>8s} {'Median':>8s} {'@1km':>6s} {'@5km':>6s} {'@10km':>6s} {'Parse':>6s} {'Time':>6s}")
    print(f"  {'-'*40} {'-'*6} {'-'*8} {'-'*8} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")

    for model in models:
        data = comparison["models"].get(model, {})
        if "error" in data:
            print(f"  {model:<40s} ERROR: {data['error'][:50]}")
            continue
        m = data["metrics"]
        print(f"  {model:<40s} {m['function_accuracy_%']:>5.1f}% {m['mean_distance_error_km']:>7.2f} {m['median_distance_error_km']:>7.2f} {m['accuracy_1km_%']:>5.1f}% {m['accuracy_5km_%']:>5.1f}% {m['accuracy_10km_%']:>5.1f}% {m['avg_parse_time_s']:>5.1f}s {m['elapsed_s']:>5.0f}s")

    print()
    print(f"  Results saved to: {args.output}")


if __name__ == "__main__":
    main()
