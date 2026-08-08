"""
Dissertation-grade evaluation metrics for SpatialParse.

Computes:
  Parsing: FMR, SCA, RI, OPA
  Computation: ADE, RDE, BE, DR, Hit@R
  Breakdown by expression type, difficulty, source

Generates LaTeX-ready tables and detailed HTML report.

Usage:
    python -m tests.dissertation_metrics
    python -m tests.dissertation_metrics --dataset datasets_extended/all_combined.json
    python -m tests.dissertation_metrics --dataset dataset/dataset_demo.json
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
logger = logging.getLogger('metrics')
logger.setLevel(logging.INFO)


# ═══════════════════════════════════════════════════════
# Independent calculator (same as test_accuracy.py)
# ═══════════════════════════════════════════════════════

_last_req = 0.0
_DIR = {'north':0,'south':180,'east':90,'west':270,'northeast':45,'northwest':315,
        'southeast':135,'southwest':225,'south west':225,'north west':315,
        'north east':45,'south east':135}


def _nominatim_raw(query):
    global _last_req
    import urllib.parse
    elapsed = time.time() - _last_req
    if elapsed < 1.2:
        time.sleep(1.2 - elapsed)
    _last_req = time.time()
    url = (f"https://nominatim.openstreetmap.org/search.php?"
           f"q={urllib.parse.quote(query)}&format=jsonv2&limit=1")
    resp = requests.get(url, headers={"User-Agent": "SpatialParseMetrics/1.0"},
                        timeout=15)
    data = resp.json()
    if not data:
        raise ValueError(f"No results for '{query}'")
    return float(data[0]['lon']), float(data[0]['lat'])


def _h_project(lon, lat, bearing_deg, dist_km):
    R = 6378.1
    brng = math.radians(bearing_deg)
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2 = math.asin(math.sin(lat1) * math.cos(dist_km / R) +
                     math.cos(lat1) * math.sin(dist_km / R) * math.cos(brng))
    lon2 = lon1 + math.atan2(math.sin(brng) * math.sin(dist_km / R) * math.cos(lat1),
                             math.cos(dist_km / R) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lon2), math.degrees(lat2)


def _h_dist(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371 * 2 * math.asin(math.sqrt(a))


def _bearing(lon1, lat1, lon2, lat2):
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _parse_dist(s):
    d = re.findall(r'[\d.]+', str(s))
    u = re.findall(r'[a-zA-Z]+', str(s))
    val = float(d[0]) if d else 1.0
    if u and u[0].lower() in ('mi','mile','miles'): val *= 1.60934
    return val


def _parse_angle(v):
    return float(re.sub(r'[^0-9.\-]', '', str(v)) or '0')


def manual_execute(steps):
    data = {}
    for step in steps:
        sid, func = step['id'], step['function']
        resolved = []
        for inp in step.get('inputs', []):
            if isinstance(inp, int) and inp in data:
                resolved.append(data[inp])
            else:
                resolved.append(inp)
        if func in ('Locate', 'Location'):
            p = resolved[0]
            data[sid] = _nominatim_raw(p) if isinstance(p, str) else p
        elif func == 'Relative':
            loc, d, dist = resolved
            lon, lat = _nominatim_raw(loc) if isinstance(loc, str) else loc
            data[sid] = _h_project(lon, lat, _DIR.get(d.lower(), 0), _parse_dist(dist))
        elif func == 'Between':
            c1 = _nominatim_raw(resolved[0]) if isinstance(resolved[0], str) else resolved[0]
            c2 = _nominatim_raw(resolved[1]) if isinstance(resolved[1], str) else resolved[1]
            data[sid] = ((c1[0]+c2[0])/2, (c1[1]+c2[1])/2)
        elif func == 'Fraction':
            c1 = _nominatim_raw(resolved[0]) if isinstance(resolved[0], str) else resolved[0]
            c2 = _nominatim_raw(resolved[1]) if isinstance(resolved[1], str) else resolved[1]
            r = float(resolved[2])
            data[sid] = (c1[0]+(c2[0]-c1[0])*r, c1[1]+(c2[1]-c1[1])*r)
        elif func == 'Azimuth':
            loc, angle, dist = resolved
            lon, lat = _nominatim_raw(loc) if isinstance(loc, str) else loc
            data[sid] = _h_project(lon, lat, _parse_angle(angle), _parse_dist(dist))
    return data


def program_execute(steps):
    from backend.geo_engine import execute_steps
    result = execute_steps(steps)
    return {sid: (float(c[0]), float(c[1])) for sid, (_, c) in result.items()}


# ═══════════════════════════════════════════════════════
# Parsing metrics
# ═══════════════════════════════════════════════════════

def compute_parsing_metrics(predicted, expected):
    """Compute FMR, SCA, RI, OPA."""
    equiv = [{'Relative', 'Azimuth'}, {'Between', 'Fraction'}]

    # SCA - Step Count Accuracy
    sca = 1.0 if len(predicted) == len(expected) else 0.0

    if len(predicted) != len(expected):
        return {'FMR': 0, 'SCA': 0, 'RI': 0, 'OPA': 0}

    # FMR - Function Match Rate
    matches = 0
    for p, e in zip(predicted, expected):
        pf, ef = p.get('function', ''), e.get('function', '')
        if pf == ef or any({pf, ef} <= eq for eq in equiv):
            matches += 1
    fmr = matches / len(expected)

    # RI - Reference Integrity
    ref_total, ref_correct = 0, 0
    for p, e in zip(predicted, expected):
        pi = [x for x in p.get('inputs', []) if isinstance(x, int)]
        ei = [x for x in e.get('inputs', []) if isinstance(x, int)]
        ref_total += max(len(pi), len(ei))
        for a, b in zip(pi, ei):
            if a == b:
                ref_correct += 1
    ri = ref_correct / ref_total if ref_total > 0 else 1.0

    opa = fmr * sca * ri
    return {'FMR': round(fmr, 4), 'SCA': round(sca, 4),
            'RI': round(ri, 4), 'OPA': round(opa, 4)}


# ═══════════════════════════════════════════════════════
# Computation metrics
# ═══════════════════════════════════════════════════════

def compute_computation_metrics(manual_pt, program_pt, steps, origin=None):
    """Compute ADE, RDE, BE, DR, Hit@R."""
    ade = _h_dist(manual_pt[0], manual_pt[1], program_pt[0], program_pt[1])

    # Extract operation distance from steps
    op_dist = 0
    for step in steps:
        for inp in step.get('inputs', []):
            m = re.search(r'(\d+)\s*(km|mi)', str(inp), re.I)
            if m:
                d = float(m.group(1))
                if 'mi' in m.group(2).lower():
                    d *= 1.609
                op_dist += d

    rde = ade / op_dist if op_dist > 0 else None

    # Bearing error (only for directional steps)
    be = None
    if origin and op_dist > 0:
        expected_bearing = _bearing(origin[0], origin[1], manual_pt[0], manual_pt[1])
        actual_bearing = _bearing(origin[0], origin[1], program_pt[0], program_pt[1])
        be = abs(expected_bearing - actual_bearing)
        if be > 180:
            be = 360 - be

    # Distance ratio
    dr = None
    if origin and op_dist > 0:
        actual_dist = _h_dist(origin[0], origin[1], program_pt[0], program_pt[1])
        dr = actual_dist / op_dist if op_dist > 0 else None

    return {
        'ADE': round(ade, 4),
        'RDE': round(rde, 4) if rde is not None else None,
        'BE': round(be, 2) if be is not None else None,
        'DR': round(dr, 4) if dr is not None else None,
        'Hit@0.1': ade < 0.1,
        'Hit@1': ade < 1.0,
        'Hit@5': ade < 5.0,
    }


def classify_type(steps):
    """Classify expression type."""
    funcs = [s['function'] for s in steps]
    if len(funcs) == 1:
        return funcs[0]
    return f"Chain({'+'.join(funcs)})"


def get_origin(steps):
    """Get the starting point name from the first step."""
    if steps and steps[0].get('inputs'):
        first_input = steps[0]['inputs'][0]
        if isinstance(first_input, str):
            try:
                return _nominatim_raw(first_input)
            except Exception:
                pass
    return None


# ═══════════════════════════════════════════════════════
# Main evaluation
# ═══════════════════════════════════════════════════════

def run_evaluation(dataset_path, max_items=None):
    with open(dataset_path, 'r', encoding='utf-8') as f:
        dataset = json.load(f)

    items = [i for i in dataset if i.get('instruction') and not any(
        isinstance(inp, str) and inp.startswith('LOC_')
        for s in i['steps'] for inp in s.get('inputs', []))]
    if max_items:
        items = items[:max_items]

    logger.info("Evaluating %d items from %s", len(items), dataset_path)

    results = []
    for item in items:
        idx = item['index']
        steps = item['steps']
        logger.info("[%d] %s", idx, item['instruction'][:60])

        entry = {
            'index': idx,
            'instruction': item['instruction'],
            'type': classify_type(steps),
            'difficulty': item.get('difficulty', 'unknown'),
            'source': item.get('source', 'unknown'),
            'n_steps': len(steps),
        }

        try:
            origin = get_origin(steps)
            md = manual_execute(steps)
            mp = md[max(md.keys())]
            pd = program_execute(steps)
            pp = pd[max(pd.keys())]

            entry['success'] = True
            entry['manual'] = mp
            entry['program'] = pp
            entry['metrics'] = compute_computation_metrics(mp, pp, steps, origin)
            logger.info("  ADE=%.4f km, Hit@1=%s", entry['metrics']['ADE'],
                        entry['metrics']['Hit@1'])
        except Exception as e:
            entry['success'] = False
            entry['error'] = str(e)
            logger.info("  ERROR: %s", e)

        results.append(entry)

    return results


# ═══════════════════════════════════════════════════════
# Reports
# ═══════════════════════════════════════════════════════

def print_summary(results):
    ok = [r for r in results if r['success']]
    metrics = [r['metrics'] for r in ok]

    print(f"\n{'='*70}")
    print(f"DISSERTATION METRICS — {len(ok)}/{len(results)} evaluated")
    print(f"{'='*70}")

    # Overall computation metrics
    ades = [m['ADE'] for m in metrics]
    print(f"\n-- Computation Accuracy --")
    print(f"  ADE (mean):   {sum(ades)/len(ades):.4f} km")
    print(f"  ADE (median): {sorted(ades)[len(ades)//2]:.4f} km")
    print(f"  ADE (max):    {max(ades):.4f} km")
    print(f"  ADE (std):    {(sum((a-sum(ades)/len(ades))**2 for a in ades)/len(ades))**0.5:.4f} km")

    rdes = [m['RDE'] for m in metrics if m['RDE'] is not None]
    if rdes:
        print(f"  RDE (mean):   {sum(rdes)/len(rdes)*100:.2f}%")

    bes = [m['BE'] for m in metrics if m['BE'] is not None]
    if bes:
        print(f"  BE (mean):    {sum(bes)/len(bes):.2f}°")

    drs = [m['DR'] for m in metrics if m['DR'] is not None]
    if drs:
        print(f"  DR (mean):    {sum(drs)/len(drs):.4f}")

    print(f"\n  Hit@0.1 km:   {sum(m['Hit@0.1'] for m in metrics)}/{len(metrics)}"
          f"  ({sum(m['Hit@0.1'] for m in metrics)/len(metrics)*100:.1f}%)")
    print(f"  Hit@1 km:     {sum(m['Hit@1'] for m in metrics)}/{len(metrics)}"
          f"  ({sum(m['Hit@1'] for m in metrics)/len(metrics)*100:.1f}%)")
    print(f"  Hit@5 km:     {sum(m['Hit@5'] for m in metrics)}/{len(metrics)}"
          f"  ({sum(m['Hit@5'] for m in metrics)/len(metrics)*100:.1f}%)")

    # By type
    print(f"\n-- By Expression Type --")
    print(f"{'Type':<30} {'N':>3} {'ADE':>8} {'RDE':>7} {'BE':>6} {'DR':>6} {'Hit@1':>7}")
    print("-" * 70)

    by_type = defaultdict(list)
    for r in ok:
        by_type[r['type']].append(r['metrics'])

    for t in sorted(by_type.keys()):
        ms = by_type[t]
        n = len(ms)
        ade_m = sum(m['ADE'] for m in ms) / n
        rdes_t = [m['RDE'] for m in ms if m['RDE'] is not None]
        rde_m = f"{sum(rdes_t)/len(rdes_t)*100:.1f}%" if rdes_t else "—"
        bes_t = [m['BE'] for m in ms if m['BE'] is not None]
        be_m = f"{sum(bes_t)/len(bes_t):.1f}°" if bes_t else "—"
        drs_t = [m['DR'] for m in ms if m['DR'] is not None]
        dr_m = f"{sum(drs_t)/len(drs_t):.3f}" if drs_t else "—"
        hit1 = f"{sum(m['Hit@1'] for m in ms)/n*100:.0f}%"
        print(f"{t:<30} {n:>3} {ade_m:>7.3f}km {rde_m:>7} {be_m:>6} {dr_m:>6} {hit1:>7}")

    # By difficulty
    print(f"\n-- By Difficulty --")
    by_diff = defaultdict(list)
    for r in ok:
        by_diff[r['difficulty']].append(r['metrics'])
    for d in ['easy', 'medium', 'hard']:
        if d not in by_diff:
            continue
        ms = by_diff[d]
        ade_m = sum(m['ADE'] for m in ms) / len(ms)
        hit1 = sum(m['Hit@1'] for m in ms) / len(ms) * 100
        print(f"  {d:<10} N={len(ms):>3}  ADE={ade_m:.3f} km  Hit@1={hit1:.0f}%")

    print(f"\n{'='*70}")


def generate_latex(results, output_path):
    """Generate LaTeX table for dissertation."""
    ok = [r for r in results if r['success']]
    by_type = defaultdict(list)
    for r in ok:
        by_type[r['type']].append(r['metrics'])

    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Computation accuracy by expression type}",
        r"\label{tab:accuracy}",
        r"\begin{tabular}{lrrrrrrr}",
        r"\hline",
        r"Expression Type & N & Mean ADE & Median ADE & RDE & BE & DR & Hit@1km \\",
        r"\hline",
    ]

    for t in sorted(by_type.keys()):
        ms = by_type[t]
        n = len(ms)
        ades = [m['ADE'] for m in ms]
        ade_mean = sum(ades) / n
        ade_med = sorted(ades)[n // 2]
        rdes = [m['RDE'] for m in ms if m['RDE'] is not None]
        rde_s = f"{sum(rdes)/len(rdes)*100:.1f}\\%" if rdes else "---"
        bes = [m['BE'] for m in ms if m['BE'] is not None]
        be_s = f"{sum(bes)/len(bes):.1f}°" if bes else "---"
        drs = [m['DR'] for m in ms if m['DR'] is not None]
        dr_s = f"{sum(drs)/len(drs):.3f}" if drs else "---"
        hit1 = sum(m['Hit@1'] for m in ms) / n * 100

        t_escaped = t.replace('_', r'\_').replace('+', r'+')
        lines.append(
            f"{t_escaped} & {n} & {ade_mean:.3f} km & {ade_med:.3f} km & "
            f"{rde_s} & {be_s} & {dr_s} & {hit1:.0f}\\% \\\\"
        )

    # Total row
    all_ades = [m['ADE'] for r in ok for m in [r['metrics']]]
    all_hit1 = sum(r['metrics']['Hit@1'] for r in ok) / len(ok) * 100
    lines.append(r"\hline")
    lines.append(
        f"\\textbf{{Total}} & {len(ok)} & {sum(all_ades)/len(all_ades):.3f} km & "
        f"{sorted(all_ades)[len(all_ades)//2]:.3f} km & --- & --- & --- & {all_hit1:.0f}\\% \\\\"
    )

    lines.extend([
        r"\hline",
        r"\end{tabular}",
        r"\end{table}",
    ])

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    logger.info("LaTeX table saved to %s", output_path)


def generate_html_report(results, output_path):
    """Generate detailed HTML report."""
    ok = [r for r in results if r['success']]
    metrics = [r['metrics'] for r in ok]
    ades = [m['ADE'] for m in metrics]

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Dissertation Metrics Report</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; margin: 0; background: #f5f5f5; }}
  .hdr {{ background: linear-gradient(135deg,#1a1a2e,#16213e); color: white; padding: 24px 32px; }}
  .hdr h1 {{ margin: 0; }} .hdr p {{ opacity: .7; margin: 4px 0 0; }}
  .content {{ max-width: 1100px; margin: 0 auto; padding: 16px; }}
  .stats {{ display: flex; gap: 12px; margin: 16px 0; flex-wrap: wrap; }}
  .st {{ background: white; padding: 16px 20px; border-radius: 8px; flex: 1; min-width: 130px;
         text-align: center; box-shadow: 0 2px 6px rgba(0,0,0,.1); }}
  .st .v {{ font-size: 28px; font-weight: bold; }} .st .l {{ color: #888; font-size: 12px; }}
  .st.g .v {{ color: #27ae60; }} .st.b .v {{ color: #2980b9; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px;
           overflow: hidden; box-shadow: 0 2px 6px rgba(0,0,0,.1); margin: 16px 0; }}
  th {{ background: #2c3e50; color: white; padding: 10px 12px; text-align: left; font-size: 12px; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #eee; font-size: 12px; }}
  tr:hover {{ background: #f0f8ff; }}
  .good {{ color: #27ae60; font-weight: bold; }}
  .warn {{ color: #e67e22; font-weight: bold; }}
  .bad {{ color: #e74c3c; font-weight: bold; }}
  h2 {{ color: #2c3e50; margin: 24px 0 8px; }}
  .formula {{ background: #f8f9fa; padding: 12px; border-radius: 6px; font-family: monospace;
              font-size: 13px; margin: 8px 0; border-left: 4px solid #3498db; }}
</style></head><body>
<div class="hdr"><h1>SpatialParse — Dissertation Metrics Report</h1>
<p>{datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(ok)}/{len(results)} tests</p></div>
<div class="content">

<h2>Metric Definitions</h2>
<div class="formula">
ADE = haversine(predicted, expected)  — Absolute Distance Error (km)<br>
RDE = ADE / D_operation  — Relative Distance Error (%)<br>
BE = |bearing(origin→predicted) - bearing(origin→expected)|  — Bearing Error (°)<br>
DR = dist(origin→predicted) / D_expected  — Distance Ratio (1.0 = perfect)<br>
Hit@R = 1 if ADE &lt; R km, else 0  — Hit Rate at radius R
</div>

<h2>Overall Results</h2>
<div class="stats">
  <div class="st g"><div class="v">{sum(m['Hit@0.1'] for m in metrics)}/{len(metrics)}</div><div class="l">Hit@0.1km</div></div>
  <div class="st g"><div class="v">{sum(m['Hit@1'] for m in metrics)}/{len(metrics)}</div><div class="l">Hit@1km</div></div>
  <div class="st b"><div class="v">{sum(ades)/len(ades):.3f}</div><div class="l">Mean ADE (km)</div></div>
  <div class="st"><div class="v">{sorted(ades)[len(ades)//2]:.3f}</div><div class="l">Median ADE (km)</div></div>
  <div class="st"><div class="v">{max(ades):.3f}</div><div class="l">Max ADE (km)</div></div>
</div>

<h2>By Expression Type</h2>
<table>
<tr><th>Type</th><th>N</th><th>Mean ADE</th><th>Median ADE</th><th>RDE</th><th>BE</th><th>DR</th><th>Hit@0.1</th><th>Hit@1</th><th>Hit@5</th></tr>
"""
    by_type = defaultdict(list)
    for r in ok:
        by_type[r['type']].append(r['metrics'])

    for t in sorted(by_type.keys()):
        ms = by_type[t]
        n = len(ms)
        a = [m['ADE'] for m in ms]
        ade_mean = sum(a)/n
        ade_med = sorted(a)[n//2]
        rdes = [m['RDE'] for m in ms if m['RDE'] is not None]
        rde_s = f"{sum(rdes)/len(rdes)*100:.1f}%" if rdes else "—"
        bes = [m['BE'] for m in ms if m['BE'] is not None]
        be_s = f"{sum(bes)/len(bes):.1f}°" if bes else "—"
        drs = [m['DR'] for m in ms if m['DR'] is not None]
        dr_s = f"{sum(drs)/len(drs):.3f}" if drs else "—"
        h01 = f"{sum(m['Hit@0.1'] for m in ms)/n*100:.0f}%"
        h1 = f"{sum(m['Hit@1'] for m in ms)/n*100:.0f}%"
        h5 = f"{sum(m['Hit@5'] for m in ms)/n*100:.0f}%"
        cls = 'good' if ade_mean < 0.1 else 'warn' if ade_mean < 2 else 'bad'
        html += f"<tr><td>{t}</td><td>{n}</td><td class='{cls}'>{ade_mean:.3f}</td>"
        html += f"<td>{ade_med:.3f}</td><td>{rde_s}</td><td>{be_s}</td><td>{dr_s}</td>"
        html += f"<td>{h01}</td><td>{h1}</td><td>{h5}</td></tr>\n"

    html += "</table>\n"

    # By difficulty
    html += "<h2>By Difficulty</h2><table>\n"
    html += "<tr><th>Difficulty</th><th>N</th><th>Mean ADE</th><th>Hit@1</th></tr>\n"
    by_diff = defaultdict(list)
    for r in ok:
        by_diff[r['difficulty']].append(r['metrics'])
    for d in ['easy', 'medium', 'hard', 'unknown']:
        if d not in by_diff: continue
        ms = by_diff[d]
        ade_m = sum(m['ADE'] for m in ms)/len(ms)
        h1 = sum(m['Hit@1'] for m in ms)/len(ms)*100
        html += f"<tr><td>{d}</td><td>{len(ms)}</td><td>{ade_m:.3f}</td><td>{h1:.0f}%</td></tr>\n"
    html += "</table>\n"

    # Full results table
    html += "<h2>All Results</h2><table>\n"
    html += "<tr><th>#</th><th>Instruction</th><th>Type</th><th>ADE</th><th>RDE</th><th>BE</th><th>DR</th><th>Hit@1</th></tr>\n"
    for r in results:
        if not r['success']:
            html += f"<tr><td>{r['index']}</td><td>{r['instruction'][:60]}...</td>"
            html += f"<td colspan='6' class='bad'>ERROR: {r.get('error','')[:40]}</td></tr>\n"
            continue
        m = r['metrics']
        cls = 'good' if m['ADE'] < 0.1 else 'warn' if m['ADE'] < 2 else 'bad'
        rde_s = f"{m['RDE']*100:.1f}%" if m['RDE'] is not None else "—"
        be_s = f"{m['BE']:.1f}°" if m['BE'] is not None else "—"
        dr_s = f"{m['DR']:.3f}" if m['DR'] is not None else "—"
        hit = '✓' if m['Hit@1'] else '✗'
        html += f"<tr><td>{r['index']}</td><td>{r['instruction'][:60]}...</td>"
        html += f"<td>{r['type']}</td><td class='{cls}'>{m['ADE']:.3f}</td>"
        html += f"<td>{rde_s}</td><td>{be_s}</td><td>{dr_s}</td><td>{hit}</td></tr>\n"
    html += "</table>\n"

    html += "</div></body></html>"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    logger.info("HTML report saved to %s", output_path)


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='dataset/dataset_demo.json')
    parser.add_argument('--max-items', type=int, default=None)
    args = parser.parse_args()

    stem = Path(args.dataset).stem

    results = run_evaluation(args.dataset, args.max_items)
    print_summary(results)

    # Save raw data
    raw_path = f'tests/metrics_{stem}.json'
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, default=str, ensure_ascii=False)
    print(f"Raw data: {raw_path}")

    # Generate reports
    latex_path = f'tests/metrics_{stem}.tex'
    generate_latex(results, latex_path)
    print(f"LaTeX table: {latex_path}")

    html_path = f'tests/metrics_{stem}.html'
    generate_html_report(results, html_path)
    print(f"HTML report: {html_path}")


if __name__ == '__main__':
    main()
