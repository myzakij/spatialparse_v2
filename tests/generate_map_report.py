"""
Generate an HTML report with interactive Folium maps for each test case.

Executes ground-truth steps from the dataset, renders results on maps,
and produces a single self-contained HTML file.

Usage:
    python -m tests.generate_map_report
    python -m tests.generate_map_report --dataset dataset/dataset_20.json
    python -m tests.generate_map_report --dataset dataset/dataset_100.json --max-items 10
"""

import json
import sys
import argparse
import time
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import folium
from folium import IFrame
from shapely.geometry import Polygon, MultiPoint

from utils.llm_coding import execute_steps, get_coordinates, to_standard_2d_list

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger('map_report')
logger.setLevel(logging.INFO)


def steps_to_readable(steps):
    parts = []
    for s in steps:
        func = s.get('function', '?')
        inputs = s.get('inputs', [])
        inputs_str = ', '.join(
            f'step#{inp}' if isinstance(inp, int)
            else f'"{inp}"' if isinstance(inp, str)
            else str(inp)
            for inp in inputs
        )
        parts.append(f'{func}({inputs_str})')
    return ' &rarr; '.join(parts)


def make_map_html(coords, centroid, title, height=350):
    """Create a Folium map and return its HTML string."""
    m = folium.Map(
        location=[centroid[1], centroid[0]],
        zoom_start=11,
        width='100%',
        height=height,
    )

    # Draw the result polygon/circle
    if isinstance(coords, list) and len(coords) >= 3:
        # Convert to [lat, lon] for Folium
        latlngs = []
        for p in coords:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                latlngs.append([p[1], p[0]])

        if latlngs:
            folium.Polygon(
                locations=latlngs,
                color='#3388ff',
                fill=True,
                fill_color='#3388ff',
                fill_opacity=0.3,
                weight=2,
                popup=title,
            ).add_to(m)

    # Mark centroid
    folium.Marker(
        location=[centroid[1], centroid[0]],
        popup=f'{title}<br>({centroid[0]:.5f}, {centroid[1]:.5f})',
        icon=folium.Icon(color='red', icon='info-sign'),
    ).add_to(m)

    return m._repr_html_()


def make_multi_step_map(all_step_data, title, height=400):
    """Create a map showing all intermediate steps with different colors."""
    colors = ['#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6',
              '#1abc9c', '#e67e22', '#2c3e50']

    # Find center from the last step
    last_key = max(all_step_data.keys())
    last_coords, last_centroid = all_step_data[last_key]

    m = folium.Map(
        location=[last_centroid[1], last_centroid[0]],
        zoom_start=8,
        width='100%',
        height=height,
    )

    for step_id in sorted(all_step_data.keys()):
        coords, centroid = all_step_data[step_id]
        color = colors[(step_id - 1) % len(colors)]
        is_last = (step_id == last_key)

        if isinstance(coords, list) and len(coords) >= 3:
            latlngs = []
            for p in coords:
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    latlngs.append([p[1], p[0]])
            if latlngs:
                folium.Polygon(
                    locations=latlngs,
                    color=color,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.35 if is_last else 0.15,
                    weight=3 if is_last else 1,
                    popup=f'Step {step_id}',
                ).add_to(m)

        # Marker for centroid
        folium.Marker(
            location=[centroid[1], centroid[0]],
            popup=f'Step {step_id}: ({centroid[0]:.4f}, {centroid[1]:.4f})',
            icon=folium.Icon(
                color='red' if is_last else 'blue',
                icon='star' if is_last else 'info-sign',
            ),
        ).add_to(m)

    # Auto-fit bounds
    all_points = []
    for coords, centroid in all_step_data.values():
        all_points.append([centroid[1], centroid[0]])
    if len(all_points) >= 2:
        m.fit_bounds(all_points, padding=[30, 30])

    return m._repr_html_()


def generate_report(dataset_path, output_path, max_items=None):
    with open(dataset_path, 'r', encoding='utf-8') as f:
        dataset = json.load(f)

    # Filter: only items with instructions and real place names
    items = [
        item for item in dataset
        if item.get('instruction') and not any(
            isinstance(inp, str) and inp.startswith('LOC_')
            for step in item['steps']
            for inp in step.get('inputs', [])
        )
    ]

    if max_items:
        items = items[:max_items]

    logger.info("Processing %d items from %s", len(items), dataset_path)

    # ---- Execute each item and collect results ----
    results = []
    for item in items:
        idx = item['index']
        instruction = item['instruction']
        steps = item['steps']

        logger.info("[%d/%d] %s", idx, len(items), instruction[:60])

        try:
            step_data = execute_steps(steps)
            final_key = max(step_data.keys())
            final_coords, final_centroid = step_data[final_key]

            results.append({
                'index': idx,
                'instruction': instruction,
                'steps': steps,
                'success': True,
                'step_data': step_data,
                'centroid': final_centroid,
            })
            logger.info("  OK - centroid=(%.4f, %.4f)", final_centroid[0], final_centroid[1])

        except Exception as e:
            logger.info("  ERROR: %s", e)
            results.append({
                'index': idx,
                'instruction': instruction,
                'steps': steps,
                'success': False,
                'error': str(e),
            })

    # ---- Generate HTML ----
    success_count = sum(1 for r in results if r['success'])
    total = len(results)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>SpatialParse Map Report</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; background: #f5f5f5; }}
  .header {{ background: linear-gradient(135deg, #52aee3, #3498db); color: white;
             padding: 30px 40px; }}
  .header h1 {{ margin: 0; font-size: 28px; }}
  .header p {{ margin: 5px 0 0; opacity: 0.8; }}
  .content {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
  .summary {{ display: flex; gap: 20px; margin: 20px 0; }}
  .stat {{ background: white; padding: 20px 30px; border-radius: 8px; flex: 1;
           box-shadow: 0 2px 8px rgba(0,0,0,0.1); text-align: center; }}
  .stat .value {{ font-size: 42px; font-weight: bold; }}
  .stat .label {{ color: #888; margin-top: 5px; }}
  .stat.green .value {{ color: #2ecc71; }}
  .stat.blue .value {{ color: #3498db; }}
  .card {{ background: white; border-radius: 8px; margin: 20px 0;
           box-shadow: 0 2px 8px rgba(0,0,0,0.1); overflow: hidden; }}
  .card-header {{ padding: 15px 20px; border-bottom: 1px solid #eee;
                  display: flex; align-items: center; gap: 12px; }}
  .card-header .idx {{ background: #52aee3; color: white; border-radius: 50%;
                       width: 32px; height: 32px; display: flex; align-items: center;
                       justify-content: center; font-weight: bold; font-size: 14px; flex-shrink: 0; }}
  .card-header .idx.fail {{ background: #e74c3c; }}
  .card-header .text {{ flex: 1; }}
  .card-header .instruction {{ font-size: 14px; color: #333; }}
  .card-header .steps {{ font-size: 12px; color: #888; font-family: Consolas, monospace; margin-top: 4px; }}
  .card-header .badge {{ padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; }}
  .badge.ok {{ background: #d4edda; color: #155724; }}
  .badge.err {{ background: #f8d7da; color: #721c24; }}
  .card-body {{ padding: 0; }}
  .card-body iframe {{ border: none; }}
  .error-msg {{ padding: 20px; color: #e74c3c; font-size: 14px; }}
  .centroid {{ font-size: 12px; color: #888; padding: 8px 20px; background: #f9f9f9;
               border-top: 1px solid #eee; }}
</style>
</head>
<body>
<div class="header">
  <h1>SpatialParse &mdash; Map Report</h1>
  <p>Dataset: {Path(dataset_path).name} &bull; {datetime.now().strftime('%Y-%m-%d %H:%M')} &bull; {total} test cases</p>
</div>
<div class="content">

<div class="summary">
  <div class="stat green">
    <div class="value">{success_count}/{total}</div>
    <div class="label">Successful</div>
  </div>
  <div class="stat blue">
    <div class="value">{success_count/total*100:.0f}%</div>
    <div class="label">Success Rate</div>
  </div>
  <div class="stat">
    <div class="value">{total - success_count}</div>
    <div class="label">Failures</div>
  </div>
</div>
"""

    for r in results:
        idx = r['index']
        instruction = r['instruction']
        steps_str = steps_to_readable(r['steps'])
        success = r['success']

        badge = '<span class="badge ok">OK</span>' if success else '<span class="badge err">FAIL</span>'
        idx_class = '' if success else ' fail'

        html += f"""
<div class="card">
  <div class="card-header">
    <div class="idx{idx_class}">{idx}</div>
    <div class="text">
      <div class="instruction">{instruction}</div>
      <div class="steps">{steps_str}</div>
    </div>
    {badge}
  </div>
  <div class="card-body">
"""

        if success:
            step_data = r['step_data']
            centroid = r['centroid']

            if len(step_data) == 1:
                key = list(step_data.keys())[0]
                coords, cent = step_data[key]
                map_html = make_map_html(coords, cent, f'#{idx}')
            else:
                map_html = make_multi_step_map(step_data, f'#{idx}')

            html += map_html
            html += f'<div class="centroid">Centroid: ({centroid[0]:.5f}, {centroid[1]:.5f})</div>\n'
        else:
            html += f'<div class="error-msg">Error: {r.get("error", "unknown")}</div>\n'

        html += '  </div>\n</div>\n'

    html += '</div>\n</body>\n</html>'

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    logger.info("Report saved to %s (%d items, %d OK)", output_path, total, success_count)
    print(f'\nReport: {output_path}')
    print(f'Results: {success_count}/{total} ({success_count/total*100:.0f}%)')


def main():
    parser = argparse.ArgumentParser(description='Generate map report')
    parser.add_argument('--dataset', default='dataset/dataset_20.json')
    parser.add_argument('--output', default=None)
    parser.add_argument('--max-items', type=int, default=None)
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f'Dataset not found: {dataset_path}')
        sys.exit(1)

    output_path = args.output or f'tests/map_report_{dataset_path.stem}.html'

    generate_report(str(dataset_path), output_path, args.max_items)


if __name__ == '__main__':
    main()
