"""
Test suite for SpatialParse HGFL pipeline (v2).

Usage:
    python -m tests.test_hgfl
    python -m tests.test_hgfl --dataset dataset/dataset_demo.json
    python -m tests.test_hgfl --exec-only
"""

import json
import sys
import time
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.llm_parser import parse as llmapi
from backend.geo_engine import execute_steps

logging.basicConfig(level=logging.WARNING, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger('test_hgfl')
logger.setLevel(logging.INFO)


def normalize_function(func_name):
    mapping = {
        'relative': 'Relative', 'between': 'Between', 'locate': 'Locate',
        'location': 'Location', 'azimuth': 'Azimuth', 'fraction': 'Fraction',
    }
    return mapping.get(func_name.lower(), func_name)


def _collapse_locate_chains(steps):
    if not steps or len(steps) < 2:
        return steps
    collapsed, skip_ids = [], set()
    for step in steps:
        if step['id'] in skip_ids:
            continue
        func = normalize_function(step.get('function', ''))
        if func == 'Locate':
            place = step['inputs'][0]
            step_id = step['id']
            for ns in steps:
                if ns['id'] in skip_ids:
                    continue
                nf = normalize_function(ns.get('function', ''))
                ni = ns.get('inputs', [])
                if ni and ni[0] == step_id and nf in ('Relative', 'Azimuth'):
                    collapsed.append({'id': ns['id'], 'function': ns['function'],
                                      'inputs': [place] + list(ni[1:])})
                    skip_ids.update([step_id, ns['id']])
                    break
            else:
                collapsed.append(step)
        else:
            collapsed.append(step)
    id_remap = {}
    for new_idx, step in enumerate(collapsed, 1):
        id_remap[step['id']] = new_idx
        step['id'] = new_idx
        step['inputs'] = [id_remap.get(i, i) if isinstance(i, int) else i for i in step['inputs']]
    return collapsed


def compare_steps(predicted, expected):
    predicted_norm = _collapse_locate_chains([dict(s) for s in predicted])
    if len(predicted_norm) != len(expected):
        return False, f"Step count: {len(predicted_norm)} (raw={len(predicted)}) vs {len(expected)}"
    for i, (pred, exp) in enumerate(zip(predicted_norm, expected)):
        pf = normalize_function(pred.get('function', ''))
        ef = normalize_function(exp.get('function', ''))
        if pf != ef:
            if {pf, ef} not in [{'Relative', 'Azimuth'}, {'Between', 'Fraction'}]:
                return False, f"Step {i+1}: {pf} vs {ef}"
        for j, (pi, ei) in enumerate(zip(pred.get('inputs', []), exp.get('inputs', []))):
            if isinstance(ei, int) and isinstance(pi, int) and pi != ei:
                return False, f"Step {i+1}: ref mismatch at {j}: {pi} vs {ei}"
    return True, "OK"


def test_parsing(dataset, max_items=None):
    items = [i for i in (dataset[:max_items] if max_items else dataset) if i.get('instruction')]
    if not items: return []
    logger.info("PARSING TEST - %d items", len(items))
    correct, results = 0, []
    for item in items:
        idx, instruction = item['index'], item['instruction']
        try:
            predicted = llmapi(instruction)
            match, detail = compare_steps(predicted, item['steps'])
            if match: correct += 1
            logger.info("[%d] %s %s", idx, "MATCH" if match else "MISS", detail if not match else "")
            results.append({'index': idx, 'match': match, 'detail': detail,
                           'predicted': predicted, 'expected': item['steps']})
        except Exception as e:
            logger.info("[%d] ERROR: %s", idx, e)
            results.append({'index': idx, 'match': False, 'detail': str(e)})
        time.sleep(1)
    logger.info("PARSING: %d/%d (%.1f%%)", correct, len(items), correct/len(items)*100)
    return results


def test_execution(dataset, max_items=None):
    items = [i for i in (dataset[:max_items] if max_items else dataset)
             if i.get('instruction') and not any(
                 isinstance(inp, str) and inp.startswith('LOC_')
                 for s in i['steps'] for inp in s.get('inputs', []))]
    if not items: return []
    logger.info("EXECUTION TEST - %d items", len(items))
    success, results = 0, []
    for item in items:
        idx = item['index']
        try:
            result = execute_steps(item['steps'])
            fk = max(result.keys())
            fc, centroid = result[fk]
            ok = isinstance(fc, list) and len(fc) > 0 and isinstance(centroid, tuple) and len(centroid) == 2
            if ok: success += 1
            logger.info("[%d] %s centroid=(%.4f, %.4f)", idx, "OK" if ok else "FAIL",
                       centroid[0] if ok else 0, centroid[1] if ok else 0)
            results.append({'index': idx, 'success': ok,
                           'centroid': centroid if ok else None,
                           'coord_count': len(fc) if isinstance(fc, list) else 0})
        except Exception as e:
            logger.info("[%d] ERROR: %s", idx, e)
            results.append({'index': idx, 'success': False, 'error': str(e)})
    logger.info("EXECUTION: %d/%d (%.1f%%)", success, len(items), success/len(items)*100)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='dataset/dataset_20.json')
    parser.add_argument('--max-items', type=int, default=None)
    parser.add_argument('--parse-only', action='store_true')
    parser.add_argument('--exec-only', action='store_true')
    args = parser.parse_args()
    with open(args.dataset, 'r', encoding='utf-8') as f:
        dataset = json.load(f)
    logger.info("Loaded %d items from %s", len(dataset), args.dataset)
    all_results = {}
    if not args.exec_only:
        all_results['parsing'] = test_parsing(dataset, args.max_items)
    if not args.parse_only:
        all_results['execution'] = test_execution(dataset, args.max_items)
    output_path = Path('tests') / f'results_{Path(args.dataset).stem}.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n{'='*60}\nSUMMARY\n{'='*60}")
    if 'parsing' in all_results:
        t = len(all_results['parsing'])
        c = sum(1 for r in all_results['parsing'] if r.get('match'))
        print(f"  Parsing:   {c}/{t} ({c/t*100:.1f}%)" if t else "  N/A")
    if 'execution' in all_results:
        t = len(all_results['execution'])
        c = sum(1 for r in all_results['execution'] if r.get('success'))
        print(f"  Execution: {c}/{t} ({c/t*100:.1f}%)" if t else "  N/A")


if __name__ == '__main__':
    main()
