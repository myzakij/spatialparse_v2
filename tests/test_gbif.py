"""
Test SpatialParse on GBIF locality descriptions (external dataset).

Filters examples with direction+distance patterns, samples 50,
runs through the system, compares with ground-truth coordinates.

Usage:
    python -m tests.test_gbif
"""

import csv
import json
import sys
import math
import re
import time
import random
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.llm_parser import parse
from backend.geo_engine import execute_steps

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("test_gbif")
logger.setLevel(logging.INFO)

SAMPLE_SIZE = 50
SEED = 42


def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371 * 2 * math.asin(math.sqrt(a))


def load_and_filter():
    """Load GBIF CSVs and filter examples with direction+distance patterns."""
    pat_dist_dir = re.compile(
        r'\d+\.?\d*\s*(km|mi|miles|m|metres|meters|ft|feet)\s*'
        r'(N|S|E|W|NE|NW|SE|SW|NNE|NNW|SSE|SSW|ENE|ESE|WNW|WSW|'
        r'north|south|east|west|northeast|northwest|southeast|southwest)',
        re.IGNORECASE
    )
    pat_dir_of = re.compile(r'(N|S|E|W|NE|NW|SE|SW|north|south|east|west)\s*of\b', re.IGNORECASE)
    pat_dist_of = re.compile(r'\d+\.?\d*\s*(km|mi|miles)\s*(of|from)\b', re.IGNORECASE)

    files = list(Path("datasets_extended/gbif").glob("*_test_data.csv"))
    candidates = []

    for fpath in files:
        with open(fpath, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                loc = row.get("locality", "")
                lat = row.get("decimalLatitude", "")
                lon = row.get("decimalLongitude", "")

                if not lat or not lon:
                    continue
                try:
                    lat_f = float(lat)
                    lon_f = float(lon)
                except ValueError:
                    continue

                # Must have direction + distance
                if pat_dist_dir.search(loc) or (pat_dist_of.search(loc) and pat_dir_of.search(loc)):
                    # Skip very long or very short descriptions
                    if 15 < len(loc) < 200:
                        # Add geographic context from metadata
                        state = row.get("stateProvince", "").strip()
                        country = row.get("countryCode", "").strip()
                        context_parts = [p for p in [state, country] if p]
                        context = ", ".join(context_parts)

                        candidates.append({
                            "locality": loc,
                            "locality_with_context": f"{loc} [{context}]" if context else loc,
                            "context": context,
                            "gold_lat": lat_f,
                            "gold_lon": lon_f,
                            "source": fpath.name,
                        })

    return candidates


def classify_complexity(text):
    """Rough complexity classification."""
    indicators = 0
    if re.search(r'then|and\s+then|proceed|continue', text, re.I):
        indicators += 2
    if text.count(",") >= 3:
        indicators += 1
    if re.findall(r'\d+\.?\d*\s*(km|mi|miles)', text, re.I).__len__() >= 2:
        indicators += 2
    if re.search(r'(near|along|between|beside|above|below)', text, re.I):
        indicators += 1
    if indicators >= 3:
        return "hard"
    elif indicators >= 1:
        return "medium"
    return "easy"


def main():
    logger.info("Loading GBIF data...")
    candidates = load_and_filter()
    logger.info("Found %d candidates with direction+distance patterns", len(candidates))

    # Stratified sample: mix of complexities and sources
    random.seed(SEED)
    random.shuffle(candidates)
    sample = candidates[:SAMPLE_SIZE]

    logger.info("Testing %d examples", len(sample))

    results = []
    start_all = time.time()

    for i, item in enumerate(sample):
        text_raw = item["locality"]
        text = item["locality_with_context"]  # with state/country appended
        gold_lat = item["gold_lat"]
        gold_lon = item["gold_lon"]
        complexity = classify_complexity(text_raw)

        logger.info("[%d/%d] %s", i+1, len(sample), text[:70])

        result = {
            "id": i + 1,
            "text_raw": text_raw,
            "text": text,
            "context": item.get("context", ""),
            "gold_lat": gold_lat,
            "gold_lon": gold_lon,
            "source": item["source"],
            "complexity": complexity,
        }

        # Parse
        t0 = time.time()
        try:
            parsed_steps = parse(text, use_fewshot=True)
            result["parsed_steps"] = parsed_steps
            result["parse_time_s"] = round(time.time() - t0, 2)
            result["parse_error"] = None
            result["functions"] = [s["function"] for s in parsed_steps]
        except Exception as e:
            logger.error("  Parse FAILED: %s", e)
            result["parse_error"] = str(e)
            result["parse_time_s"] = round(time.time() - t0, 2)
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

            dist_err = haversine(pred_lon, pred_lat, gold_lon, gold_lat)
            result["distance_error_km"] = round(dist_err, 3)

            logger.info("  OK: err=%.2f km | %s", dist_err,
                        " → ".join(result["functions"]))
        except Exception as e:
            logger.error("  Exec FAILED: %s", e)
            result["exec_error"] = str(e)
            result["exec_time_s"] = round(time.time() - t1, 2)
            result["distance_error_km"] = None

        results.append(result)

    elapsed = round(time.time() - start_all, 1)

    # Metrics
    successful = [r for r in results if r.get("distance_error_km") is not None]
    distances = sorted([r["distance_error_km"] for r in successful])
    n = len(distances)

    if n > 0:
        mean = sum(distances) / n
        median = distances[n//2] if n % 2 else (distances[n//2-1] + distances[n//2]) / 2
        acc1 = sum(1 for d in distances if d < 1) / n * 100
        acc5 = sum(1 for d in distances if d < 5) / n * 100
        acc10 = sum(1 for d in distances if d < 10) / n * 100
        acc25 = sum(1 for d in distances if d < 25) / n * 100
        acc50 = sum(1 for d in distances if d < 50) / n * 100
    else:
        mean = median = acc1 = acc5 = acc10 = acc25 = acc50 = 0

    parse_errors = sum(1 for r in results if r.get("parse_error"))
    exec_errors = sum(1 for r in results if not r.get("parse_error") and r.get("distance_error_km") is None)

    # Per complexity
    by_complexity = {}
    for r in results:
        c = r.get("complexity", "?")
        if c not in by_complexity:
            by_complexity[c] = {"total": 0, "distances": []}
        by_complexity[c]["total"] += 1
        if r.get("distance_error_km") is not None:
            by_complexity[c]["distances"].append(r["distance_error_km"])

    summary = {
        "timestamp": datetime.now().isoformat(),
        "dataset": "GBIF Locality Descriptions (Figshare)",
        "total_candidates": len(load_and_filter()),
        "sample_size": len(sample),
        "successful": n,
        "parse_errors": parse_errors,
        "exec_errors": exec_errors,
        "elapsed_s": elapsed,
        "metrics": {
            "mean_distance_error_km": round(mean, 2),
            "median_distance_error_km": round(median, 2),
            "min_error_km": round(min(distances), 2) if distances else 0,
            "max_error_km": round(max(distances), 2) if distances else 0,
            "accuracy_1km_%": round(acc1, 1),
            "accuracy_5km_%": round(acc5, 1),
            "accuracy_10km_%": round(acc10, 1),
            "accuracy_25km_%": round(acc25, 1),
            "accuracy_50km_%": round(acc50, 1),
        },
    }

    output = {"summary": summary, "results": results}
    out_path = Path("tests/gbif_test_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Print
    print("\n" + "=" * 70)
    print("  GBIF EXTERNAL DATASET TEST RESULTS")
    print("=" * 70)
    print(f"  Source: GBIF Locality Descriptions (Figshare)")
    print(f"  Candidates with direction+distance: {summary['total_candidates']}")
    print(f"  Sample tested: {len(sample)}")
    print(f"  Successful: {n}, Parse errors: {parse_errors}, Exec errors: {exec_errors}")
    print(f"  Time: {elapsed}s")
    print()
    print(f"  METRICS:")
    print(f"    Mean error:    {mean:.2f} km")
    print(f"    Median error:  {median:.2f} km")
    print(f"    Min / Max:     {min(distances):.2f} / {max(distances):.2f} km" if distances else "")
    print(f"    Accuracy @1km:  {acc1:.1f}%")
    print(f"    Accuracy @5km:  {acc5:.1f}%")
    print(f"    Accuracy @10km: {acc10:.1f}%")
    print(f"    Accuracy @25km: {acc25:.1f}%")
    print(f"    Accuracy @50km: {acc50:.1f}%")
    print()
    print(f"  BY COMPLEXITY:")
    for c in ["easy", "medium", "hard"]:
        info = by_complexity.get(c, {"total": 0, "distances": []})
        ds = info["distances"]
        if ds:
            m = sum(ds) / len(ds)
            med = sorted(ds)[len(ds)//2]
            a5 = sum(1 for d in ds if d < 5) / len(ds) * 100
            print(f"    {c:8s}  n={info['total']:2d}  mean={m:.1f} km  median={med:.1f} km  @5km={a5:.0f}%")
        else:
            print(f"    {c:8s}  n={info['total']:2d}  no successful results")
    print(f"\n  Results saved to: {out_path}")


if __name__ == "__main__":
    main()
