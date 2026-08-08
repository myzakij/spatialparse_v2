"""
Accuracy test v2: independent manual calculation vs program output.
Generates HTML report with Leaflet maps showing both results.

Usage:
    python -m tests.test_accuracy
    python -m tests.test_accuracy --dataset dataset/dataset_demo.json
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

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger('test_accuracy')
logger.setLevel(logging.INFO)

# ── Independent calculator (NO program code used) ──

_last_req = 0.0

def _nominatim_raw(query):
    global _last_req
    import urllib.parse
    elapsed = time.time() - _last_req
    if elapsed < 1.2:
        time.sleep(1.2 - elapsed)
    _last_req = time.time()
    url = (f"https://nominatim.openstreetmap.org/search.php?"
           f"q={urllib.parse.quote(query)}&format=jsonv2&limit=1")
    resp = requests.get(url, headers={"User-Agent": "SpatialParseTest/1.0"}, timeout=15)
    data = resp.json()
    if not data:
        raise ValueError(f"Nominatim: no results for '{query}'")
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
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return 6371 * 2 * math.asin(math.sqrt(a))

_DIR = {'north':0,'south':180,'east':90,'west':270,'northeast':45,'northwest':315,
        'southeast':135,'southwest':225,'south west':225,'north west':315,
        'north east':45,'south east':135}

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
            l1, l2 = resolved
            c1 = _nominatim_raw(l1) if isinstance(l1, str) else l1
            c2 = _nominatim_raw(l2) if isinstance(l2, str) else l2
            data[sid] = ((c1[0]+c2[0])/2, (c1[1]+c2[1])/2)
        elif func == 'Fraction':
            l1, l2, r = resolved
            c1 = _nominatim_raw(l1) if isinstance(l1, str) else l1
            c2 = _nominatim_raw(l2) if isinstance(l2, str) else l2
            r = float(r)
            data[sid] = (c1[0]+(c2[0]-c1[0])*r, c1[1]+(c2[1]-c1[1])*r)
        elif func == 'Azimuth':
            loc, angle, dist = resolved
            lon, lat = _nominatim_raw(loc) if isinstance(loc, str) else loc
            data[sid] = _h_project(lon, lat, _parse_angle(angle), _parse_dist(dist))
    return data

# ── Program executor ──

def program_execute(steps):
    from backend.geo_engine import execute_steps
    result = execute_steps(steps)
    return {sid: (float(c[0]), float(c[1])) for sid, (_, c) in result.items()}

# ── HTML Report with Leaflet maps ──

def generate_report(results, dataset, output_path):
    total = len(results)
    ok_results = [r for r in results if r['success']]
    dists = [r['dist'] for r in ok_results]
    exact = sum(1 for d in dists if d < 0.1)
    good = sum(1 for d in dists if d < 2)
    avg = sum(dists)/len(dists) if dists else 0
    med = sorted(dists)[len(dists)//2] if dists else 0
    mx = max(dists) if dists else 0

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Accuracy Report v2</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; margin: 0; background: #f5f5f5; }}
  .hdr {{ background: linear-gradient(135deg,#2c3e50,#3498db); color: white; padding: 24px 32px; }}
  .hdr h1 {{ margin: 0; }} .hdr p {{ opacity: .7; margin: 4px 0 0; }}
  .content {{ max-width: 1100px; margin: 0 auto; padding: 16px; }}
  .stats {{ display: flex; gap: 12px; margin: 16px 0; flex-wrap: wrap; }}
  .st {{ background: white; padding: 16px 20px; border-radius: 8px; flex: 1; min-width: 120px;
         text-align: center; box-shadow: 0 2px 6px rgba(0,0,0,.1); }}
  .st .v {{ font-size: 28px; font-weight: bold; }} .st .l {{ color: #888; font-size: 12px; }}
  .st.g .v {{ color: #27ae60; }} .st.b .v {{ color: #2980b9; }} .st.o .v {{ color: #e67e22; }}
  .card {{ background: white; border-radius: 8px; margin: 16px 0; overflow: hidden;
           box-shadow: 0 2px 6px rgba(0,0,0,.1); }}
  .card-h {{ padding: 12px 16px; border-bottom: 1px solid #eee; display: flex; align-items: center; gap: 10px; }}
  .card-h .n {{ background: #3498db; color: white; border-radius: 50%; width: 28px; height: 28px;
                display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 13px; }}
  .card-h .n.bad {{ background: #e74c3c; }} .card-h .n.warn {{ background: #e67e22; }}
  .card-h .txt {{ flex: 1; font-size: 13px; }}
  .badge {{ padding: 3px 8px; border-radius: 10px; font-size: 11px; font-weight: bold; }}
  .badge.g {{ background: #d5f5e3; color: #1e8449; }}
  .badge.o {{ background: #fef9e7; color: #b7950b; }}
  .badge.r {{ background: #fadbd8; color: #922b21; }}
  .mapbox {{ height: 350px; }}
  .info {{ padding: 10px 16px; font-size: 12px; background: #f9f9f9; border-top: 1px solid #eee; }}
  .err {{ padding: 14px 16px; color: #e74c3c; }}
</style></head><body>
<div class="hdr"><h1>SpatialParse v2 — Accuracy Report</h1>
<p>Manual calculation vs Program | {datetime.now().strftime('%Y-%m-%d %H:%M')} | {total} tests</p></div>
<div class="content">
<div class="stats">
  <div class="st g"><div class="v">{exact}/{len(ok_results)}</div><div class="l">Exact (&lt;100m)</div></div>
  <div class="st b"><div class="v">{good}/{len(ok_results)}</div><div class="l">Good (&lt;2km)</div></div>
  <div class="st o"><div class="v">{avg:.2f} km</div><div class="l">Mean error</div></div>
  <div class="st"><div class="v">{med:.2f} km</div><div class="l">Median</div></div>
  <div class="st {'g' if mx < 5 else 'o'}"><div class="v">{mx:.2f} km</div><div class="l">Max</div></div>
</div>
<p style="font-size:13px;color:#888">
  <span style="color:#3498db">&#9679;</span> Blue = manual (independent math)
  &nbsp;<span style="color:#e74c3c">&#9733;</span> Red = program
  &nbsp;<span style="color:#e74c3c">- - -</span> difference
</p>
"""
    for r in results:
        idx = r['index']
        item = next((d for d in dataset if d['index'] == idx), {})
        instr = item.get('instruction', '')
        dist = r['dist']
        if not r['success']:
            badge, nc = '<span class="badge r">ERROR</span>', 'bad'
        elif dist < 2:
            badge, nc = f'<span class="badge g">{dist:.2f} km</span>', ''
        elif dist < 20:
            badge, nc = f'<span class="badge o">{dist:.1f} km</span>', 'warn'
        else:
            badge, nc = f'<span class="badge r">{dist:.1f} km</span>', 'bad'

        html += f'<div class="card"><div class="card-h"><div class="n {nc}">{idx}</div>'
        html += f'<div class="txt">{instr}</div>{badge}</div>'

        if r['success']:
            mp, pp = r['manual'], r['program']
            mid_lat, mid_lon = (mp[1]+pp[1])/2, (mp[0]+pp[0])/2
            mid = f'{map_id}' if 'map_id' in dir() else f'map{idx}'
            map_id = f'map{idx}'
            html += f'<div class="mapbox" id="{map_id}"></div>'
            line_js = ""
            if dist > 0.01:
                line_js = f"L.polyline([[{mp[1]},{mp[0]}],[{pp[1]},{pp[0]}]],{{color:'#e74c3c',weight:2,dashArray:'6',opacity:.6}}).addTo(m);"
            html += f"""<script>
(function(){{
  var m=L.map('{map_id}').setView([{mid_lat},{mid_lon}],11);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'OSM'}}).addTo(m);
  L.marker([{mp[1]},{mp[0]}],{{icon:L.divIcon({{className:'',html:'<div style="width:20px;height:20px;border-radius:50%;background:#3498db;border:2px solid white;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>',iconSize:[20,20],iconAnchor:[10,10]}})}}
  ).addTo(m).bindPopup('<b>Manual</b><br>({mp[0]:.5f}, {mp[1]:.5f})');
  L.marker([{pp[1]},{pp[0]}],{{icon:L.divIcon({{className:'',html:'<div style="width:22px;height:22px;border-radius:50%;background:#e74c3c;border:2px solid white;box-shadow:0 1px 3px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;color:white;font-size:12px">★</div>',iconSize:[22,22],iconAnchor:[11,11]}})}}
  ).addTo(m).bindPopup('<b>Program</b><br>({pp[0]:.5f}, {pp[1]:.5f})');
  {line_js}
  m.fitBounds([[{mp[1]},{mp[0]}],[{pp[1]},{pp[0]}]],{{padding:[60,60]}});
}})();
</script>"""
            html += f'<div class="info">Manual: ({mp[0]:.5f}, {mp[1]:.5f}) | '
            html += f'Program: ({pp[0]:.5f}, {pp[1]:.5f}) | '
            html += f'<b>Diff: {dist:.2f} km</b></div>'
        else:
            html += f'<div class="err">{r.get("error","unknown")}</div>'
        html += '</div>'

    html += '</div></body></html>'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='dataset/dataset_demo.json')
    parser.add_argument('--output', default=None)
    parser.add_argument('--max-items', type=int, default=None)
    args = parser.parse_args()

    with open(args.dataset, 'r', encoding='utf-8') as f:
        dataset = json.load(f)

    items = [i for i in dataset if i.get('instruction') and not any(
        isinstance(inp, str) and inp.startswith('LOC_')
        for s in i['steps'] for inp in s.get('inputs', []))]
    if args.max_items:
        items = items[:args.max_items]

    logger.info("Testing %d items", len(items))
    results = []

    for item in items:
        idx = item['index']
        logger.info("[%d] %s", idx, item['instruction'][:60])
        try:
            md = manual_execute(item['steps'])
            mp = md[max(md.keys())]
            pd = program_execute(item['steps'])
            pp = pd[max(pd.keys())]
            dist = _h_dist(mp[0], mp[1], pp[0], pp[1])
            logger.info("  Manual=(%.5f,%.5f) Program=(%.5f,%.5f) Diff=%.2f km",
                        mp[0], mp[1], pp[0], pp[1], dist)
            results.append({'index': idx, 'success': True, 'manual': mp, 'program': pp, 'dist': dist})
        except Exception as e:
            logger.info("  ERROR: %s", e)
            results.append({'index': idx, 'success': False, 'dist': 999, 'error': str(e)})

    ok = [r for r in results if r['success']]
    dists = [r['dist'] for r in ok]
    print(f"\n{'='*60}")
    print(f"RESULTS: {len(ok)}/{len(results)} executed")
    if dists:
        print(f"  Exact (<0.1 km): {sum(1 for d in dists if d<0.1)}/{len(ok)}")
        print(f"  Good (<2 km):    {sum(1 for d in dists if d<2)}/{len(ok)}")
        print(f"  Mean: {sum(dists)/len(dists):.2f} km | Median: {sorted(dists)[len(dists)//2]:.2f} km | Max: {max(dists):.2f} km")
    print(f"{'='*60}")

    output = args.output or f'tests/accuracy_v2_{Path(args.dataset).stem}.html'
    generate_report(results, dataset, output)
    print(f"Report: {output}")


if __name__ == '__main__':
    main()
