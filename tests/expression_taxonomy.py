"""
Expression Taxonomy for SpatialParse.

Defines what the system CAN and CANNOT handle.
Generates a formal classification document for the dissertation.

Usage:
    python -m tests.expression_taxonomy
"""

import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))


# ═══════════════════════════════════════════════════════
# TAXONOMY
# ═══════════════════════════════════════════════════════

SUPPORTED = {
    "absolute_reference": {
        "name": "Absolute Spatial Reference",
        "description": "Direct reference to a named geographic entity",
        "function": "Locate",
        "examples": [
            "Find Central Park in New York",
            "Where is the Eiffel Tower?",
            "Locate Kazan Kremlin",
        ],
        "constraints": [
            "Place must exist in OpenStreetMap/Nominatim",
            "Ambiguous names resolved via LLM context (Portland OR vs ME)",
            "Supports Latin and Cyrillic place names",
        ],
        "accuracy": "Depends on Nominatim data quality",
    },

    "cardinal_direction": {
        "name": "Cardinal Direction + Distance",
        "description": "Offset from a place in one of 4 cardinal directions (N/S/E/W)",
        "function": "Relative",
        "examples": [
            "5 km south of the Eiffel Tower",
            "20 km north of Murmansk",
            "3 km east of Big Ben",
        ],
        "constraints": [
            "Direction must be one of: north, south, east, west",
            "Distance must include a numeric value and unit (km, miles, meters)",
        ],
        "accuracy": "ADE < 0.01 km (Haversine projection)",
    },

    "ordinal_direction": {
        "name": "Ordinal Direction + Distance",
        "description": "Offset in one of 4 ordinal directions (NE/NW/SE/SW)",
        "function": "Relative",
        "examples": [
            "3 km northeast of Central Park",
            "7 km southwest of Kazan Kremlin",
            "10 km southeast of Sydney Opera House",
        ],
        "constraints": [
            "Direction: northeast, northwest, southeast, southwest",
            "Bearing fixed at 45/135/225/315 degrees",
        ],
        "accuracy": "ADE < 0.01 km",
    },

    "azimuth_bearing": {
        "name": "Specific Compass Bearing + Distance",
        "description": "Offset at an exact bearing angle in degrees",
        "function": "Azimuth",
        "examples": [
            "8 km at bearing 120 degrees from Sydney Opera House",
            "50 km at 210 degrees from Santiago",
            "4 km at 36 degrees from Jasper",
        ],
        "constraints": [
            "Bearing: 0-360 degrees (0=North, 90=East, 180=South, 270=West)",
            "Accepts degree symbol: 120, 120deg, 120 degrees",
        ],
        "accuracy": "ADE < 0.01 km",
    },

    "midpoint": {
        "name": "Midpoint Between Two Places",
        "description": "Geographic center point between two locations",
        "function": "Between",
        "examples": [
            "Midpoint between Paris and London",
            "Halfway between Kremlin and Sheremetyevo",
            "Center between Colosseum and Pantheon",
        ],
        "constraints": [
            "Both places must be geocodable",
            "Uses linear interpolation of coordinates (not great circle)",
            "Works at any scale: local (1 km) to international (10000 km)",
        ],
        "accuracy": "ADE < 0.05 km",
    },

    "fractional_position": {
        "name": "Fractional Position Between Two Places",
        "description": "Point at a specific fraction along the line between two locations",
        "function": "Fraction",
        "examples": [
            "One-quarter of the way from Burwood to Sydney Town Hall",
            "Three-quarters from Statue of Liberty to Times Square",
            "Two-thirds of the way from Vladivostok to Khabarovsk",
        ],
        "constraints": [
            "Ratio: 0.0 (at location1) to 1.0 (at location2)",
            "Natural language fractions: 'quarter' -> 0.25, 'third' -> 0.33",
        ],
        "accuracy": "ADE < 0.3 km (depends on geocoding consistency)",
    },

    "chain_sequential": {
        "name": "Sequential Chain (2 steps)",
        "description": "Two positioning operations applied in sequence",
        "function": "Multiple",
        "examples": [
            "6 km east of Big Ben, then 4 km south",
            "15 km NW of Kremlin, then midpoint to Sheremetyevo",
            "Midpoint of A and B, then 2 km north",
        ],
        "constraints": [
            "Each step references the result of the previous step",
            "Supports any combination of Relative, Between, Azimuth, Fraction",
        ],
        "accuracy": "ADE < 0.1 km (errors do not accumulate with Haversine)",
    },

    "chain_complex": {
        "name": "Complex Chain (3+ steps)",
        "description": "Three or more positioning operations in sequence",
        "function": "Multiple",
        "examples": [
            "From Kremlin 7 km SW, then 4 km azimuth 200, midpoint to Kazan Station, 3 km N, 2 km E",
            "Start at Golden Gate, 5 km SE, 3 km SW, midpoint to Alcatraz",
            "From Edinburgh Castle 2 km E, 3 km N, then 4 km at 70 degrees",
        ],
        "constraints": [
            "Maximum tested: 5 steps",
            "LLM must correctly parse all step references",
            "Parsing accuracy decreases with chain length",
        ],
        "accuracy": "ADE < 0.2 km for 3 steps, < 0.5 km for 5 steps",
    },

    "russian_language": {
        "name": "Russian Language Input",
        "description": "Spatial descriptions in Russian, auto-translated to English",
        "function": "Any",
        "examples": [
            "5 km k yugu ot Eiffelevoj bashni",
            "Seredina mezhdu Kremlyom i Sheremetyevo",
            "10 km na severo-zapad ot Kazanskogo Kremlya",
        ],
        "constraints": [
            "Cyrillic text auto-detected and translated via LLM",
            "Place names converted to standard English (Kazan, Moscow)",
            "Directions translated (k severu -> north)",
            "Translation cached in SQLite for consistency",
        ],
        "accuracy": "Same as English equivalent after translation",
    },

    "compound_direction": {
        "name": "Compound Direction Description",
        "description": "Non-standard directional descriptions converted to bearing",
        "function": "Azimuth",
        "examples": [
            "10 degrees west of south -> 190 degrees",
            "Bearing 045 from location",
        ],
        "constraints": [
            "LLM interprets compound directions and converts to numeric bearing",
        ],
        "accuracy": "Depends on LLM interpretation accuracy",
    },
}


NOT_SUPPORTED = {
    "temporal_spatial": {
        "name": "Temporal-Spatial Expressions",
        "description": "Locations that depend on time or movement",
        "examples": [
            "Where the hurricane will be in 6 hours",
            "The ship's position tomorrow at noon",
            "5 km from where I was yesterday",
        ],
        "reason": "System processes static spatial descriptions, not temporal trajectories",
    },

    "relative_to_self": {
        "name": "Self-Referential Positions",
        "description": "Locations relative to the user's current position",
        "examples": [
            "3 km north of here",
            "The nearest hospital",
            "5 minutes walk from my location",
        ],
        "reason": "System has no access to user's GPS coordinates",
    },

    "route_planning": {
        "name": "Route Planning / Navigation",
        "description": "Optimal paths between locations considering roads",
        "examples": [
            "Fastest route from A to B",
            "Drive 10 minutes north on Highway 1",
            "Walking distance to the station",
        ],
        "reason": "System computes geometric positions, not routes. OSRM integration is for visualization only",
    },

    "area_containment": {
        "name": "Area Containment / Topology",
        "description": "Spatial relationships like 'inside', 'outside', 'bordering'",
        "examples": [
            "Hotels inside Central Park",
            "Cities bordering France",
            "Restaurants within 500m of the river",
        ],
        "reason": "System handles point-based positioning, not polygon intersection queries",
    },

    "fuzzy_distance": {
        "name": "Vague / Fuzzy Distances",
        "description": "Non-numeric distance descriptions",
        "examples": [
            "A short walk from the station",
            "Not far from the city center",
            "A few hours drive south",
        ],
        "reason": "System requires explicit numeric distances. 'nearby' and 'close' are not supported in HGFL pipeline",
    },

    "altitude_3d": {
        "name": "3D / Altitude Positioning",
        "description": "Vertical spatial references",
        "examples": [
            "500 meters above sea level",
            "The 30th floor of the building",
            "At the summit of the mountain",
        ],
        "reason": "System operates in 2D (lon/lat). No elevation data used",
    },

    "historical_places": {
        "name": "Historical / Non-Existent Places",
        "description": "Places that no longer exist or have changed names",
        "examples": [
            "Constantinople (now Istanbul)",
            "The Berlin Wall checkpoint",
            "Stalingrad city center",
        ],
        "reason": "Nominatim indexes current OSM data. Historical names may not resolve. LLM may help with well-known renamings",
    },

    "multi_result": {
        "name": "Multiple Result Locations",
        "description": "Queries that should return multiple points",
        "examples": [
            "All Starbucks within 5 km of Times Square",
            "Three equidistant points between A and B",
            "Every intersection along Main Street",
        ],
        "reason": "System returns a single result area per query. No POI search capability",
    },

    "indoor_positioning": {
        "name": "Indoor / Micro-Scale Positioning",
        "description": "Sub-building level spatial references",
        "examples": [
            "Room 305 in the north wing",
            "Third aisle of the supermarket",
            "Gate B12 at the airport",
        ],
        "reason": "Nominatim resolution is ~building level. No indoor mapping",
    },
}


# ═══════════════════════════════════════════════════════
# Report generation
# ═══════════════════════════════════════════════════════

def generate_report(output_path):
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Expression Taxonomy</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; margin: 0; background: #f5f5f5; }}
  .hdr {{ background: linear-gradient(135deg,#1a1a2e,#16213e); color: white; padding: 24px 32px; }}
  .hdr h1 {{ margin: 0; }} .hdr p {{ opacity: .7; margin: 4px 0 0; }}
  .content {{ max-width: 1000px; margin: 0 auto; padding: 16px; }}
  h2 {{ color: #2c3e50; margin: 24px 0 12px; border-bottom: 2px solid #3498db; padding-bottom: 6px; }}
  h3 {{ color: #16213e; margin: 16px 0 8px; }}
  .card {{ background: white; border-radius: 8px; padding: 16px 20px; margin: 10px 0;
           box-shadow: 0 2px 6px rgba(0,0,0,.1); }}
  .card.supported {{ border-left: 4px solid #27ae60; }}
  .card.unsupported {{ border-left: 4px solid #e74c3c; }}
  .card h4 {{ margin: 0 0 6px; }}
  .card .desc {{ color: #555; font-size: 13px; margin-bottom: 8px; }}
  .card .func {{ display: inline-block; background: #eef6ff; color: #2980b9; padding: 2px 8px;
                 border-radius: 4px; font-size: 11px; font-weight: 600; margin-bottom: 6px; }}
  .card .func.red {{ background: #fef0f0; color: #e74c3c; }}
  .examples {{ margin: 6px 0; }}
  .examples code {{ display: block; background: #f8f9fa; padding: 4px 8px; margin: 3px 0;
                    border-radius: 4px; font-size: 12px; color: #333; }}
  .constraints {{ font-size: 12px; color: #888; margin: 6px 0; }}
  .constraints li {{ margin: 2px 0; }}
  .accuracy {{ font-size: 12px; color: #27ae60; font-weight: 600; margin-top: 6px; }}
  .reason {{ font-size: 12px; color: #e74c3c; margin-top: 6px; font-style: italic; }}
  .summary {{ background: white; padding: 16px 20px; border-radius: 8px; margin: 16px 0;
              box-shadow: 0 2px 6px rgba(0,0,0,.1); }}
  .summary table {{ width: 100%; border-collapse: collapse; }}
  .summary th {{ text-align: left; padding: 6px 8px; border-bottom: 2px solid #ddd; font-size: 12px; }}
  .summary td {{ padding: 6px 8px; border-bottom: 1px solid #eee; font-size: 12px; }}
  .tag {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 10px;
          font-weight: 600; margin: 1px; }}
  .tag.green {{ background: #d5f5e3; color: #1e8449; }}
  .tag.red {{ background: #fadbd8; color: #922b21; }}
</style></head><body>
<div class="hdr">
  <h1>SpatialParse Expression Taxonomy</h1>
  <p>Formal classification of supported and unsupported spatial expressions | {datetime.now().strftime('%Y-%m-%d')}</p>
</div>
<div class="content">

<div class="summary">
<table>
<tr><th>Category</th><th>Count</th><th>Status</th></tr>
<tr><td>Supported expression types</td><td>{len(SUPPORTED)}</td><td><span class="tag green">SUPPORTED</span></td></tr>
<tr><td>Unsupported expression types</td><td>{len(NOT_SUPPORTED)}</td><td><span class="tag red">NOT SUPPORTED</span></td></tr>
<tr><td>Functions available</td><td>5</td><td>Locate, Relative, Between, Fraction, Azimuth</td></tr>
<tr><td>Maximum chain length (tested)</td><td>5 steps</td><td>Longer chains possible but untested</td></tr>
<tr><td>Languages</td><td>2</td><td>English, Russian (auto-translated)</td></tr>
</table>
</div>

<h2>Supported Expressions</h2>
"""

    for key, item in SUPPORTED.items():
        html += f"""<div class="card supported">
  <span class="func">{item.get('function', '?')}</span>
  <h4>{item['name']}</h4>
  <div class="desc">{item['description']}</div>
  <div class="examples">"""
        for ex in item['examples']:
            html += f'<code>"{ex}"</code>\n'
        html += '</div><ul class="constraints">\n'
        for c in item.get('constraints', []):
            html += f'<li>{c}</li>\n'
        html += f'</ul>\n<div class="accuracy">{item.get("accuracy", "")}</div>\n</div>\n'

    html += '<h2>Not Supported</h2>\n'

    for key, item in NOT_SUPPORTED.items():
        html += f"""<div class="card unsupported">
  <span class="func red">NOT SUPPORTED</span>
  <h4>{item['name']}</h4>
  <div class="desc">{item['description']}</div>
  <div class="examples">"""
        for ex in item['examples']:
            html += f'<code>"{ex}"</code>\n'
        html += f'</div>\n<div class="reason">Reason: {item["reason"]}</div>\n</div>\n'

    html += '</div></body></html>'

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Report: {output_path}")


def print_summary():
    print(f"\n{'='*70}")
    print("EXPRESSION TAXONOMY")
    print(f"{'='*70}")

    print(f"\n-- SUPPORTED ({len(SUPPORTED)} types) --")
    for key, item in SUPPORTED.items():
        func = item.get('function', '?')
        print(f"  [{func:>10}] {item['name']}")
        print(f"             Example: \"{item['examples'][0]}\"")
        print(f"             Accuracy: {item.get('accuracy', '?')}")

    print(f"\n-- NOT SUPPORTED ({len(NOT_SUPPORTED)} types) --")
    for key, item in NOT_SUPPORTED.items():
        print(f"  [   ---    ] {item['name']}")
        print(f"             Example: \"{item['examples'][0]}\"")
        print(f"             Reason: {item['reason']}")

    print(f"\n{'='*70}")


def main():
    print_summary()
    output = 'tests/expression_taxonomy.html'
    generate_report(output)


if __name__ == '__main__':
    main()
