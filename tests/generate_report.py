"""
Generate a human-readable HTML report from test results.

Usage:
    python -m tests.generate_report
    python -m tests.generate_report --results tests/results_dataset_100.json
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))


def load_dataset(dataset_path):
    """Load dataset to get instruction texts."""
    with open(dataset_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {item['index']: item for item in data}


def steps_to_readable(steps):
    """Convert step list to readable string."""
    parts = []
    for s in steps:
        func = s.get('function', '?')
        inputs = s.get('inputs', [])
        inputs_str = ', '.join(
            f'step#{inp}' if isinstance(inp, int) else f'"{inp}"' if isinstance(inp, str) else str(inp)
            for inp in inputs
        )
        parts.append(f'{func}({inputs_str})')
    return ' → '.join(parts)


def generate_html(results_path, dataset_path, output_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        results = json.load(f)

    dataset = load_dataset(dataset_path)

    parsing = results.get('parsing', [])
    execution = results.get('execution', [])

    parse_ok = sum(1 for r in parsing if r.get('match'))
    parse_total = len(parsing)
    exec_ok = sum(1 for r in execution if r.get('success'))
    exec_total = len(execution)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>SpatialParse Test Report</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
  h1 {{ color: #333; border-bottom: 3px solid #52aee3; padding-bottom: 10px; }}
  h2 {{ color: #52aee3; margin-top: 30px; }}
  .summary {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin: 20px 0; }}
  .summary .metric {{ display: inline-block; margin: 10px 30px 10px 0; }}
  .metric .value {{ font-size: 36px; font-weight: bold; }}
  .metric .label {{ color: #666; font-size: 14px; }}
  .metric.good .value {{ color: #2ecc71; }}
  .metric.warn .value {{ color: #f39c12; }}
  .metric.bad .value {{ color: #e74c3c; }}
  .bar {{ background: #eee; border-radius: 4px; height: 24px; margin: 5px 0 15px; overflow: hidden; }}
  .bar .fill {{ height: 100%; border-radius: 4px; display: flex; align-items: center; padding-left: 8px;
                color: white; font-weight: bold; font-size: 13px; }}
  .bar .fill.green {{ background: #2ecc71; }}
  .bar .fill.orange {{ background: #f39c12; }}
  .bar .fill.red {{ background: #e74c3c; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px;
           overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin: 10px 0 30px; }}
  th {{ background: #52aee3; color: white; padding: 12px 10px; text-align: left; font-size: 13px; }}
  td {{ padding: 10px; border-bottom: 1px solid #eee; font-size: 13px; vertical-align: top; }}
  tr:hover {{ background: #f0f8ff; }}
  .pass {{ color: #2ecc71; font-weight: bold; }}
  .fail {{ color: #e74c3c; font-weight: bold; }}
  .steps {{ font-family: 'Consolas', monospace; font-size: 12px; color: #555; word-break: break-all; }}
  .instruction {{ max-width: 400px; }}
  .detail {{ color: #e74c3c; font-size: 12px; }}
  .legend {{ background: #fff; padding: 15px; border-radius: 8px; margin: 20px 0; font-size: 13px;
             box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .legend b {{ color: #52aee3; }}
</style>
</head>
<body>
<h1>SpatialParse &mdash; Test Report</h1>
<p style="color:#888">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} &bull;
   Dataset: {Path(dataset_path).name} ({parse_total} items)</p>

<div class="summary">
  <div class="metric {'good' if parse_ok/parse_total >= 0.8 else 'warn' if parse_ok/parse_total >= 0.6 else 'bad'}">
    <div class="value">{parse_ok/parse_total*100:.1f}%</div>
    <div class="label">Parsing Accuracy ({parse_ok}/{parse_total})</div>
  </div>
  <div class="metric {'good' if exec_ok/exec_total >= 0.9 else 'warn' if exec_ok/exec_total >= 0.7 else 'bad'}">
    <div class="value">{exec_ok/exec_total*100:.1f}%</div>
    <div class="label">Execution Success ({exec_ok}/{exec_total})</div>
  </div>
</div>

<div class="bar"><div class="fill {'green' if parse_ok/parse_total >= 0.8 else 'orange'}"
     style="width:{parse_ok/parse_total*100}%">Parsing: {parse_ok}/{parse_total}</div></div>
<div class="bar"><div class="fill {'green' if exec_ok/exec_total >= 0.9 else 'orange'}"
     style="width:{exec_ok/exec_total*100}%">Execution: {exec_ok}/{exec_total}</div></div>

<div class="legend">
  <b>Parsing test</b> &mdash; checks that the LLM correctly converts natural language instructions into
  a sequence of positioning functions (Relative, Between, Azimuth, Fraction, Locate).<br>
  <b>Execution test</b> &mdash; runs ground-truth step chains through geocoding (Nominatim) and
  verifies that valid coordinates are produced.
</div>
"""

    # ---- PARSING TABLE ----
    html += '<h2>Parsing Results</h2>\n'
    html += '<table>\n<tr><th>#</th><th>Result</th><th class="instruction">Instruction</th>'
    html += '<th>Expected Steps</th><th>Predicted Steps</th><th>Detail</th></tr>\n'

    for r in parsing:
        idx = r['index']
        instruction = dataset.get(idx, {}).get('instruction', '—')
        match = r.get('match', False)
        expected = r.get('expected', [])
        predicted = r.get('predicted', [])
        detail = r.get('detail', '')

        status_class = 'pass' if match else 'fail'
        status_text = '&#10004;' if match else '&#10008;'

        exp_str = steps_to_readable(expected) if expected else '—'
        pred_str = steps_to_readable(predicted) if predicted else '—'
        detail_html = f'<span class="detail">{detail}</span>' if not match else ''

        html += f'<tr><td>{idx}</td><td class="{status_class}">{status_text}</td>'
        html += f'<td class="instruction">{instruction[:120]}{"..." if len(instruction) > 120 else ""}</td>'
        html += f'<td class="steps">{exp_str}</td>'
        html += f'<td class="steps">{pred_str}</td>'
        html += f'<td>{detail_html}</td></tr>\n'

    html += '</table>\n'

    # ---- EXECUTION TABLE ----
    html += '<h2>Execution Results</h2>\n'
    html += '<table>\n<tr><th>#</th><th>Result</th><th class="instruction">Instruction</th>'
    html += '<th>Steps</th><th>Centroid</th><th>Points</th></tr>\n'

    for r in execution:
        idx = r['index']
        instruction = dataset.get(idx, {}).get('instruction', '—')
        steps = dataset.get(idx, {}).get('steps', [])
        success = r.get('success', False)
        centroid = r.get('centroid')
        coord_count = r.get('coord_count', 0)
        error = r.get('error', '')

        status_class = 'pass' if success else 'fail'
        status_text = '&#10004;' if success else '&#10008;'

        steps_str = steps_to_readable(steps)

        if centroid:
            centroid_str = f'({centroid[0]:.4f}, {centroid[1]:.4f})'
        elif error:
            centroid_str = f'<span class="detail">{error[:80]}</span>'
        else:
            centroid_str = '—'

        html += f'<tr><td>{idx}</td><td class="{status_class}">{status_text}</td>'
        html += f'<td class="instruction">{instruction[:120]}{"..." if len(instruction) > 120 else ""}</td>'
        html += f'<td class="steps">{steps_str}</td>'
        html += f'<td>{centroid_str}</td>'
        html += f'<td>{coord_count}</td></tr>\n'

    html += '</table>\n'

    # ---- MISMATCH ANALYSIS ----
    mismatches = [r for r in parsing if not r.get('match')]
    if mismatches:
        html += '<h2>Mismatch Analysis</h2>\n'

        reasons = {}
        for m in mismatches:
            detail = m.get('detail', 'unknown')
            key = detail.split(':')[0].strip()
            reasons[key] = reasons.get(key, 0) + 1

        html += '<table><tr><th>Reason</th><th>Count</th><th>%</th></tr>\n'
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            pct = count / parse_total * 100
            html += f'<tr><td>{reason}</td><td>{count}</td><td>{pct:.1f}%</td></tr>\n'
        html += '</table>\n'

    html += '</body></html>'

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'Report saved to: {output_path}')
    return output_path


def main():
    parser = argparse.ArgumentParser(description='Generate HTML test report')
    parser.add_argument('--results', default='tests/results_dataset_100.json')
    parser.add_argument('--dataset', default=None,
                       help='Path to dataset JSON (auto-detected from results filename)')
    parser.add_argument('--output', default=None)
    args = parser.parse_args()

    results_path = Path(args.results)
    if not results_path.exists():
        print(f'Results file not found: {results_path}')
        sys.exit(1)

    # Auto-detect dataset path from results filename
    if args.dataset:
        dataset_path = Path(args.dataset)
    else:
        stem = results_path.stem.replace('results_', '')
        dataset_path = Path('dataset') / f'{stem}.json'
        if not dataset_path.exists():
            # Try common names
            for candidate in ['dataset_100.json', 'dataset_20.json', 'test.json']:
                p = Path('dataset') / candidate
                if p.exists():
                    dataset_path = p
                    break

    if not dataset_path.exists():
        print(f'Dataset file not found: {dataset_path}')
        sys.exit(1)

    output_path = args.output or str(results_path.with_suffix('.html'))

    generate_html(str(results_path), str(dataset_path), output_path)


if __name__ == '__main__':
    main()
