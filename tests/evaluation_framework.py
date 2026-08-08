"""
Evaluation Framework for SpatialParse.

Defines:
1. Taxonomy of supported spatial expressions
2. Parsing accuracy metrics (text → function chain)
3. Computation accuracy metrics (function chain → coordinates)
4. Classification of test results

Usage:
    python -m tests.evaluation_framework
    python -m tests.evaluation_framework --dataset dataset/dataset_demo.json
"""

import json
import sys
import math
import time
import re
import logging
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger('evaluation')
logger.setLevel(logging.INFO)


# =====================================================
# 1. TAXONOMY — types of spatial expressions
# =====================================================

EXPRESSION_TYPES = {
    # --- Single-step expressions ---
    'locate': {
        'description': 'Simple place lookup',
        'example': 'Find Central Park in New York',
        'functions': ['Locate'],
        'complexity': 'easy',
    },
    'relative_cardinal': {
        'description': 'Direction + distance from a place (cardinal: N/S/E/W)',
        'example': '5 km south of the Eiffel Tower',
        'functions': ['Relative'],
        'complexity': 'easy',
    },
    'relative_ordinal': {
        'description': 'Direction + distance from a place (ordinal: NE/NW/SE/SW)',
        'example': '3 km northeast of Central Park',
        'functions': ['Relative'],
        'complexity': 'easy',
    },
    'between_simple': {
        'description': 'Midpoint between two places',
        'example': 'Midpoint between Colosseum and Pantheon',
        'functions': ['Between'],
        'complexity': 'easy',
    },
    'azimuth': {
        'description': 'Specific compass bearing + distance',
        'example': '8 km at bearing 120° from Sydney Opera House',
        'functions': ['Azimuth'],
        'complexity': 'easy',
    },
    'fraction': {
        'description': 'Fractional position between two places',
        'example': 'One-quarter of the way from A to B',
        'functions': ['Fraction'],
        'complexity': 'medium',
    },

    # --- Multi-step expressions ---
    'chain_relative_relative': {
        'description': 'Two sequential directional offsets',
        'example': '6 km east of Big Ben, then 4 km south',
        'functions': ['Relative', 'Relative'],
        'complexity': 'medium',
    },
    'chain_between_relative': {
        'description': 'Midpoint, then directional offset',
        'example': 'Midpoint of A and B, then 2 km north',
        'functions': ['Between', 'Relative'],
        'complexity': 'medium',
    },
    'chain_relative_between': {
        'description': 'Directional offset, then midpoint with another place',
        'example': '15 km NW of Kremlin, then midpoint to Sheremetyevo',
        'functions': ['Relative', 'Between'],
        'complexity': 'medium',
    },
    'chain_relative_azimuth': {
        'description': 'Cardinal offset followed by bearing offset',
        'example': '7 km SW of X, then 3 km at bearing 200°',
        'functions': ['Relative', 'Azimuth'],
        'complexity': 'hard',
    },
    'chain_azimuth_between': {
        'description': 'Bearing offset, then midpoint with another place',
        'example': '12 km bearing 45° from X, midpoint to Y',
        'functions': ['Azimuth', 'Between'],
        'complexity': 'hard',
    },
    'chain_3plus_steps': {
        'description': '3 or more chained operations',
        'example': '5km SE of A, 3km SW, midpoint to B',
        'functions': ['*', '*', '*'],
        'complexity': 'hard',
    },
}

# Geographic scale categories
SCALE_CATEGORIES = {
    'local': {'max_km': 10, 'description': 'Within a city (< 10 km)'},
    'regional': {'max_km': 100, 'description': 'Between nearby cities (10-100 km)'},
    'national': {'max_km': 1000, 'description': 'Within a country (100-1000 km)'},
    'international': {'max_km': float('inf'), 'description': 'Between countries (> 1000 km)'},
}


def classify_expression(steps):
    """Classify a step chain into an expression type."""
    funcs = [s['function'] for s in steps]
    n = len(funcs)

    if n == 1:
        f = funcs[0]
        if f == 'Locate' or f == 'Location':
            return 'locate'
        elif f == 'Relative':
            direction = str(steps[0]['inputs'][1]).lower() if len(steps[0]['inputs']) > 1 else ''
            if direction in ('north', 'south', 'east', 'west'):
                return 'relative_cardinal'
            else:
                return 'relative_ordinal'
        elif f == 'Between':
            return 'between_simple'
        elif f == 'Azimuth':
            return 'azimuth'
        elif f == 'Fraction':
            return 'fraction'
    elif n == 2:
        key = f'chain_{"_".join(f.lower() for f in funcs)}'
        if key in EXPRESSION_TYPES:
            return key
        # Check reversed
        key_rev = f'chain_{"_".join(f.lower() for f in reversed(funcs))}'
        if key_rev in EXPRESSION_TYPES:
            return key_rev
        return 'chain_relative_relative'  # fallback for 2-step
    elif n >= 3:
        return 'chain_3plus_steps'

    return 'unknown'


def classify_scale(steps):
    """Estimate geographic scale from step parameters."""
    total_distance = 0
    for step in steps:
        inputs = step.get('inputs', [])
        for inp in inputs:
            if isinstance(inp, str):
                # Try to extract distance
                match = re.search(r'(\d+)\s*(km|mi|mile)', str(inp), re.I)
                if match:
                    km = float(match.group(1))
                    if match.group(2).lower() in ('mi', 'mile'):
                        km *= 1.609
                    total_distance += km

        # Check if Between with far-apart places
        if step['function'] == 'Between':
            str_inputs = [str(i) for i in inputs if isinstance(i, str)]
            if len(str_inputs) >= 2:
                # Heuristic: different countries = international
                countries1 = re.findall(r'(France|Japan|Germany|Italy|USA|Peru|Mexico|Greece|Iceland|Spain|Australia)', str_inputs[0], re.I)
                countries2 = re.findall(r'(France|Japan|Germany|Italy|USA|Peru|Mexico|Greece|Iceland|Spain|Australia)', str_inputs[1], re.I)
                if countries1 and countries2 and countries1[0].lower() != countries2[0].lower():
                    return 'international'

    if total_distance == 0:
        return 'local'
    elif total_distance <= 10:
        return 'local'
    elif total_distance <= 100:
        return 'regional'
    elif total_distance <= 1000:
        return 'national'
    return 'international'


# =====================================================
# 2. ACCURACY METRICS
# =====================================================

def compute_parsing_metrics(predicted_steps, expected_steps):
    """Compute parsing accuracy metrics.

    Returns dict with:
        - function_match: bool — do functions match in order?
        - step_count_match: bool — same number of steps?
        - reference_match: bool — do int references match?
        - overall_match: bool — all of the above
    """
    pred_funcs = [s['function'] for s in predicted_steps]
    exp_funcs = [s['function'] for s in expected_steps]

    step_count_match = len(pred_funcs) == len(exp_funcs)

    # Function sequence match (allowing Relative<->Azimuth, Between<->Fraction)
    equiv = {'Relative', 'Azimuth'}
    equiv2 = {'Between', 'Fraction'}
    func_match = step_count_match
    if step_count_match:
        for p, e in zip(pred_funcs, exp_funcs):
            if p != e and not ({p, e} <= equiv or {p, e} <= equiv2):
                func_match = False
                break

    # Reference match
    ref_match = True
    if step_count_match:
        for p, e in zip(predicted_steps, expected_steps):
            p_refs = [i for i in p.get('inputs', []) if isinstance(i, int)]
            e_refs = [i for i in e.get('inputs', []) if isinstance(i, int)]
            if p_refs != e_refs:
                ref_match = False
                break

    return {
        'step_count_match': step_count_match,
        'function_match': func_match,
        'reference_match': ref_match,
        'overall_match': step_count_match and func_match and ref_match,
    }


def compute_computation_metrics(manual_point, program_point, steps):
    """Compute computation accuracy metrics.

    Returns dict with:
        - absolute_error_km: distance between manual and program result
        - relative_error: error relative to the scale of the operation
        - accuracy_grade: 'exact' / 'good' / 'acceptable' / 'poor' / 'wrong'
    """
    abs_err = _haversine(manual_point[0], manual_point[1],
                         program_point[0], program_point[1])

    # Estimate operation scale (total distances involved)
    total_dist = 0
    for step in steps:
        for inp in step.get('inputs', []):
            if isinstance(inp, str):
                match = re.search(r'(\d+)\s*(km|mi)', str(inp), re.I)
                if match:
                    km = float(match.group(1))
                    if 'mi' in match.group(2).lower():
                        km *= 1.609
                    total_dist += km

    if total_dist > 0:
        relative_err = abs_err / total_dist
    else:
        relative_err = abs_err / 10  # default scale 10 km

    # Grade
    if abs_err < 0.1:
        grade = 'exact'
    elif abs_err < 2:
        grade = 'good'
    elif abs_err < 10:
        grade = 'acceptable'
    elif abs_err < 50:
        grade = 'poor'
    else:
        grade = 'wrong'

    return {
        'absolute_error_km': abs_err,
        'relative_error': relative_err,
        'accuracy_grade': grade,
    }


def _haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


# =====================================================
# 3. REPORT
# =====================================================

def print_evaluation_report(results, dataset):
    """Print comprehensive evaluation report to console."""

    print("\n" + "=" * 70)
    print("EVALUATION FRAMEWORK — SpatialParse")
    print("=" * 70)

    # --- Taxonomy breakdown ---
    print("\n## 1. SUPPORTED EXPRESSION TYPES")
    print("-" * 70)

    type_counts = defaultdict(int)
    type_results = defaultdict(list)
    scale_counts = defaultdict(int)
    complexity_counts = defaultdict(int)

    for r in results:
        item = next((d for d in dataset if d['index'] == r['index']), {})
        steps = item.get('steps', [])
        expr_type = classify_expression(steps)
        scale = classify_scale(steps)
        complexity = EXPRESSION_TYPES.get(expr_type, {}).get('complexity', 'unknown')

        type_counts[expr_type] += 1
        type_results[expr_type].append(r)
        scale_counts[scale] += 1
        complexity_counts[complexity] += 1

    print(f"\n{'Type':<30} {'Count':>5} {'Avg Error':>10} {'Grade':>10}")
    print("-" * 60)
    for expr_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        errors = [r['abs_err'] for r in type_results[expr_type] if r.get('success')]
        avg_err = sum(errors) / len(errors) if errors else float('inf')
        info = EXPRESSION_TYPES.get(expr_type, {})
        grade = 'exact' if avg_err < 0.1 else 'good' if avg_err < 2 else 'acceptable' if avg_err < 10 else 'poor'
        print(f"{expr_type:<30} {count:>5} {avg_err:>9.2f}km {grade:>10}")

    # --- Scale breakdown ---
    print(f"\n{'Scale':<20} {'Count':>5}")
    print("-" * 30)
    for scale, count in sorted(scale_counts.items()):
        print(f"{scale:<20} {count:>5}")

    # --- Complexity breakdown ---
    print(f"\n{'Complexity':<20} {'Count':>5}")
    print("-" * 30)
    for comp, count in sorted(complexity_counts.items()):
        print(f"{comp:<20} {count:>5}")

    # --- Accuracy summary ---
    print("\n\n## 2. ACCURACY METRICS")
    print("-" * 70)

    successful = [r for r in results if r.get('success')]
    errors_km = [r['abs_err'] for r in successful]

    if errors_km:
        print(f"\nComputation Accuracy (manual vs program):")
        print(f"  Total tests:    {len(results)}")
        print(f"  Successful:     {len(successful)}")
        print(f"  Failed:         {len(results) - len(successful)}")
        print()
        print(f"  Exact (< 0.1 km):     {sum(1 for e in errors_km if e < 0.1):>3}/{len(successful)}"
              f"  ({sum(1 for e in errors_km if e < 0.1)/len(successful)*100:.0f}%)")
        print(f"  Good (< 2 km):        {sum(1 for e in errors_km if e < 2):>3}/{len(successful)}"
              f"  ({sum(1 for e in errors_km if e < 2)/len(successful)*100:.0f}%)")
        print(f"  Acceptable (< 10 km): {sum(1 for e in errors_km if e < 10):>3}/{len(successful)}"
              f"  ({sum(1 for e in errors_km if e < 10)/len(successful)*100:.0f}%)")
        print(f"  Poor (< 50 km):       {sum(1 for e in errors_km if e < 50):>3}/{len(successful)}"
              f"  ({sum(1 for e in errors_km if e < 50)/len(successful)*100:.0f}%)")
        print(f"  Wrong (>= 50 km):     {sum(1 for e in errors_km if e >= 50):>3}/{len(successful)}"
              f"  ({sum(1 for e in errors_km if e >= 50)/len(successful)*100:.0f}%)")
        print()
        print(f"  Mean error:     {sum(errors_km)/len(errors_km):.2f} km")
        print(f"  Median error:   {sorted(errors_km)[len(errors_km)//2]:.2f} km")
        print(f"  Max error:      {max(errors_km):.2f} km")
        print(f"  Std deviation:  {(sum((e - sum(errors_km)/len(errors_km))**2 for e in errors_km)/len(errors_km))**0.5:.2f} km")

    # --- Accuracy by type ---
    print("\n\n## 3. ACCURACY BY EXPRESSION TYPE")
    print("-" * 70)
    print(f"{'Type':<30} {'Tests':>5} {'Exact':>6} {'Good':>6} {'Accept':>7} {'Mean':>8}")
    print("-" * 70)
    for expr_type in sorted(type_counts.keys()):
        type_errs = [r['abs_err'] for r in type_results[expr_type] if r.get('success')]
        n = len(type_errs)
        if n == 0:
            continue
        exact = sum(1 for e in type_errs if e < 0.1)
        good = sum(1 for e in type_errs if e < 2)
        accept = sum(1 for e in type_errs if e < 10)
        mean = sum(type_errs) / n
        print(f"{expr_type:<30} {n:>5} {exact:>5}  {good:>5}  {accept:>6}  {mean:>7.2f}km")

    # --- Recommendations ---
    print("\n\n## 4. RECOMMENDATIONS")
    print("-" * 70)

    best_types = [t for t, rs in type_results.items()
                  if all(r.get('success') and r['abs_err'] < 2 for r in rs)]
    ok_types = [t for t, rs in type_results.items()
                if all(r.get('success') and r['abs_err'] < 10 for r in rs) and t not in best_types]
    problem_types = [t for t in type_counts if t not in best_types and t not in ok_types]

    if best_types:
        print("\n  BEST performance (all results < 2 km error):")
        for t in best_types:
            info = EXPRESSION_TYPES.get(t, {})
            print(f"    + {t}: {info.get('description', '')}")
            print(f"      Example: {info.get('example', '')}")

    if ok_types:
        print("\n  ACCEPTABLE performance (all results < 10 km error):")
        for t in ok_types:
            info = EXPRESSION_TYPES.get(t, {})
            print(f"    ~ {t}: {info.get('description', '')}")

    if problem_types:
        print("\n  NEEDS IMPROVEMENT (some results > 10 km error):")
        for t in problem_types:
            info = EXPRESSION_TYPES.get(t, {})
            errs = [r['abs_err'] for r in type_results[t] if r.get('success')]
            max_err = max(errs) if errs else 0
            print(f"    ! {t}: max error {max_err:.1f} km")

    print("\n" + "=" * 70)


# =====================================================
# MAIN — run evaluation on dataset
# =====================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='dataset/dataset_demo.json')
    parser.add_argument('--accuracy-results', default=None,
                       help='Path to accuracy_report JSON (if already computed)')
    args = parser.parse_args()

    with open(args.dataset, 'r', encoding='utf-8') as f:
        dataset = json.load(f)

    # Load or compute accuracy results
    results_path = args.accuracy_results
    if not results_path:
        # Try to find existing results
        stem = Path(args.dataset).stem
        candidate = Path(f'tests/accuracy_data_{stem}.json')
        if candidate.exists():
            results_path = str(candidate)

    if results_path and Path(results_path).exists():
        with open(results_path, 'r', encoding='utf-8') as f:
            results = json.load(f)
    else:
        # Run accuracy test
        logger.info("Running accuracy tests (this may take a while)...")
        from tests.test_accuracy import manual_execute, program_execute, _haversine_dist

        items = [
            item for item in dataset
            if item.get('instruction') and not any(
                isinstance(inp, str) and inp.startswith('LOC_')
                for step in item['steps']
                for inp in step.get('inputs', [])
            )
        ]

        results = []
        for item in items:
            idx = item['index']
            steps = item['steps']
            logger.info("[%d] %s", idx, item.get('instruction', '')[:60])

            try:
                manual_data = manual_execute(steps)
                manual_key = max(manual_data.keys())
                mp = manual_data[manual_key]

                program_data = program_execute(steps)
                program_key = max(program_data.keys())
                pp = program_data[program_key]

                abs_err = _haversine_dist(mp[0], mp[1], pp[0], pp[1])

                results.append({
                    'index': idx,
                    'success': True,
                    'abs_err': abs_err,
                    'manual_point': mp,
                    'program_point': pp,
                })
            except Exception as e:
                results.append({
                    'index': idx,
                    'success': False,
                    'abs_err': 999,
                    'error': str(e),
                })

        # Save results
        save_path = f'tests/accuracy_data_{Path(args.dataset).stem}.json'
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info("Saved accuracy data to %s", save_path)

    print_evaluation_report(results, dataset)


if __name__ == '__main__':
    main()
