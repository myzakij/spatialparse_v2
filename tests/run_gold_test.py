"""
Run gold_standard.json through the system and produce a results file.

Usage:
    python -m tests.run_gold_test
"""

import json
import sys
import math
import time
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.llm_parser import parse
from backend.geo_engine import execute_steps

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("gold_test")
logger.setLevel(logging.INFO)


def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371 * 2 * math.asin(math.sqrt(a))


def compare_steps(predicted, expected):
    """Compare predicted steps with expected. Returns dict with metrics."""
    if not predicted or not expected:
        return {"function_match": False, "step_count_match": False, "exact_match": False}

    step_count_match = len(predicted) == len(expected)

    # Compare functions
    pred_funcs = [s.get("function") for s in predicted]
    exp_funcs = [s.get("function") for s in expected]
    func_match = pred_funcs == exp_funcs

    # Exact match (function + inputs structure)
    exact = True
    if len(predicted) != len(expected):
        exact = False
    else:
        for p, e in zip(predicted, expected):
            if p.get("function") != e.get("function"):
                exact = False
                break

    return {
        "function_match": func_match,
        "step_count_match": step_count_match,
        "exact_match": exact,
        "predicted_functions": pred_funcs,
        "expected_functions": exp_funcs,
    }


def run_test(dataset_path, output_path):
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    results = []
    errors_parse = 0
    errors_exec = 0
    total = len(dataset)

    logger.info("Starting test: %d examples from %s", total, dataset_path)
    start_all = time.time()

    for i, item in enumerate(dataset):
        idx = item["id"]
        text = item["text"]
        category = item["category"]
        difficulty = item.get("difficulty", "?")
        gold_lon = item["gold_lon"]
        gold_lat = item["gold_lat"]
        expected_steps = item.get("expected_steps", [])

        logger.info("[%d/%d] id=%d cat=%s: %s", i+1, total, idx, category, text[:60])

        result = {
            "id": idx,
            "text": text,
            "category": category,
            "difficulty": difficulty,
            "gold_lon": gold_lon,
            "gold_lat": gold_lat,
        }

        # Phase 1: Parse
        t0 = time.time()
        try:
            parsed_steps = parse(text, use_fewshot=True)
            result["parsed_steps"] = parsed_steps
            result["parse_time_s"] = round(time.time() - t0, 2)
            result["parse_error"] = None
        except Exception as e:
            logger.error("  Parse FAILED: %s", e)
            result["parsed_steps"] = None
            result["parse_time_s"] = round(time.time() - t0, 2)
            result["parse_error"] = str(e)
            errors_parse += 1
            results.append(result)
            continue

        # Compare steps
        step_cmp = compare_steps(parsed_steps, expected_steps)
        result.update(step_cmp)

        # Phase 2: Execute
        t1 = time.time()
        try:
            step_data = execute_steps(parsed_steps)
            result["exec_time_s"] = round(time.time() - t1, 2)
            result["exec_error"] = None

            # Get final centroid
            final_key = max(step_data.keys())
            _, final_centroid = step_data[final_key]
            pred_lon = round(final_centroid[0], 5)
            pred_lat = round(final_centroid[1], 5)

            result["pred_lon"] = pred_lon
            result["pred_lat"] = pred_lat

            # Distance error
            dist_err = haversine(pred_lon, pred_lat, gold_lon, gold_lat)
            result["distance_error_km"] = round(dist_err, 3)

            logger.info("  OK: pred=(%.4f,%.4f) gold=(%.4f,%.4f) err=%.2f km | func_match=%s",
                        pred_lon, pred_lat, gold_lon, gold_lat, dist_err, step_cmp["function_match"])

        except Exception as e:
            logger.error("  Execute FAILED: %s", e)
            result["exec_time_s"] = round(time.time() - t1, 2)
            result["exec_error"] = str(e)
            result["pred_lon"] = None
            result["pred_lat"] = None
            result["distance_error_km"] = None
            errors_exec += 1

        results.append(result)

    elapsed = round(time.time() - start_all, 1)

    # ── Aggregate metrics ──
    successful = [r for r in results if r.get("distance_error_km") is not None]
    distances = [r["distance_error_km"] for r in successful]

    if distances:
        distances_sorted = sorted(distances)
        n = len(distances_sorted)
        median = distances_sorted[n // 2] if n % 2 else (distances_sorted[n//2 - 1] + distances_sorted[n//2]) / 2
        mean = sum(distances) / len(distances)
        acc_1 = sum(1 for d in distances if d < 1) / len(distances) * 100
        acc_5 = sum(1 for d in distances if d < 5) / len(distances) * 100
        acc_10 = sum(1 for d in distances if d < 10) / len(distances) * 100
        max_err = max(distances)
        min_err = min(distances)
    else:
        median = mean = acc_1 = acc_5 = acc_10 = max_err = min_err = 0

    func_matches = sum(1 for r in results if r.get("function_match"))
    func_accuracy = func_matches / total * 100 if total > 0 else 0

    # Per-category metrics
    categories = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"total": 0, "successful": 0, "distances": [], "func_matches": 0}
        categories[cat]["total"] += 1
        if r.get("distance_error_km") is not None:
            categories[cat]["successful"] += 1
            categories[cat]["distances"].append(r["distance_error_km"])
        if r.get("function_match"):
            categories[cat]["func_matches"] += 1

    cat_summary = {}
    for cat, info in sorted(categories.items()):
        ds = info["distances"]
        ds_sorted = sorted(ds) if ds else []
        n = len(ds_sorted)
        cat_summary[cat] = {
            "total": info["total"],
            "successful": info["successful"],
            "func_accuracy_%": round(info["func_matches"] / info["total"] * 100, 1) if info["total"] else 0,
            "mean_error_km": round(sum(ds)/len(ds), 3) if ds else None,
            "median_error_km": round(ds_sorted[n//2], 3) if n % 2 and ds else (round((ds_sorted[n//2-1]+ds_sorted[n//2])/2, 3) if ds else None),
            "accuracy_1km_%": round(sum(1 for d in ds if d < 1)/len(ds)*100, 1) if ds else 0,
            "accuracy_5km_%": round(sum(1 for d in ds if d < 5)/len(ds)*100, 1) if ds else 0,
        }

    summary = {
        "timestamp": datetime.now().isoformat(),
        "dataset": str(dataset_path),
        "total_examples": total,
        "successful": len(successful),
        "parse_errors": errors_parse,
        "exec_errors": errors_exec,
        "elapsed_s": elapsed,
        "overall_metrics": {
            "mean_distance_error_km": round(mean, 3),
            "median_distance_error_km": round(median, 3),
            "min_error_km": round(min_err, 3),
            "max_error_km": round(max_err, 3),
            "accuracy_1km_%": round(acc_1, 1),
            "accuracy_5km_%": round(acc_5, 1),
            "accuracy_10km_%": round(acc_10, 1),
            "function_accuracy_%": round(func_accuracy, 1),
        },
        "per_category": cat_summary,
    }

    output = {
        "summary": summary,
        "results": results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Print summary
    print("\n" + "="*60)
    print(f"  GOLD STANDARD TEST RESULTS")
    print(f"  {total} examples, {len(successful)} successful, {errors_parse} parse errors, {errors_exec} exec errors")
    print(f"  Time: {elapsed}s")
    print("="*60)
    print(f"\n  OVERALL METRICS:")
    print(f"    Mean distance error:   {mean:.2f} km")
    print(f"    Median distance error: {median:.2f} km")
    print(f"    Min / Max error:       {min_err:.2f} / {max_err:.2f} km")
    print(f"    Accuracy @1 km:        {acc_1:.1f}%")
    print(f"    Accuracy @5 km:        {acc_5:.1f}%")
    print(f"    Accuracy @10 km:       {acc_10:.1f}%")
    print(f"    Function accuracy:     {func_accuracy:.1f}%")
    print(f"\n  PER CATEGORY:")
    for cat, info in sorted(cat_summary.items()):
        me = f"{info['mean_error_km']:.2f} km" if info['mean_error_km'] is not None else "N/A"
        print(f"    {cat:15s}  n={info['total']:2d}  func={info['func_accuracy_%']:5.1f}%  mean_err={me:>8s}  @5km={info['accuracy_5km_%']:.0f}%")
    print(f"\n  Results saved to: {output_path}")


if __name__ == "__main__":
    dataset_path = Path("dataset/gold_standard.json")
    output_path = Path("tests/gold_test_results.json")
    run_test(dataset_path, output_path)
