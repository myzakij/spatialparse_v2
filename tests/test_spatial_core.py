import math
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import geo_engine


def _centroid(result):
    return result[1]


def _fake_circle(center, radius=0.1):
    lon, lat = center
    return [
        (lon, lat + radius),
        (lon + radius, lat),
        (lon, lat - radius),
        (lon - radius, lat),
        (lon, lat + radius),
    ]


class SpatialCoreTests(unittest.TestCase):
    def setUp(self):
        self.places = {
            "A": ((0.0, 0.0), 1.0),
            "B": ((2.0, 0.0), 1.0),
            "North": ((0.0, 2.0), 1.0),
            "Landmark": ((1.0, 0.0), 0.5),
            "City": ((10.0, 10.0), 5.0),
        }

    def fake_get_coordinates(self, place):
        center, radius = self.places[str(place)]
        return _fake_circle(center), center, radius

    def test_execute_all_core_functions_without_network(self):
        steps = [
            {"id": 1, "function": "Locate", "inputs": ["A"]},
            {"id": 2, "function": "Relative", "inputs": [1, "north", "1 km"]},
            {"id": 3, "function": "Between", "inputs": ["A", "B"]},
            {"id": 4, "function": "Fraction", "inputs": ["A", "B", 0.25]},
            {"id": 5, "function": "Azimuth", "inputs": ["A", 90, "1 km"]},
            {"id": 6, "function": "Toward", "inputs": ["A", "North", "1 km"]},
            {"id": 7, "function": "Near", "inputs": ["A", "adjacent"]},
        ]

        with patch("backend.geo_engine.get_coordinates", side_effect=self.fake_get_coordinates):
            result = geo_engine.execute_steps(steps, uncertainty=True)

        self.assertEqual(set(result), {1, 2, 3, 4, 5, 6, 7})
        self.assertGreater(_centroid(result[2])[1], 0.0)
        self.assertAlmostEqual(_centroid(result[3])[0], 1.0)
        self.assertAlmostEqual(_centroid(result[4])[0], 0.5)
        self.assertGreater(_centroid(result[5])[0], 0.0)
        self.assertGreater(_centroid(result[6])[1], 0.0)
        self.assertGreater(len(result[7][0]), 10)

    def test_along_uses_route_geometry(self):
        with patch("backend.geo_engine.road_route", return_value=([(0.0, 0.0), (0.0, 0.02)], 2.2)):
            coords, center = geo_engine.along((0.0, 0.0), (0.0, 0.02), "1 km")

        self.assertGreater(center[1], 0.0)
        self.assertLess(center[1], 0.02)
        self.assertGreater(len(coords), 3)

    def test_intersection_and_street_turn_without_overpass(self):
        def fake_street_geometry(street, city=None):
            return {
                "First": [(0.0, -1.0), (0.0, 0.0), (0.0, 1.0)],
                "Second": [(-1.0, 0.0), (0.0, 0.0), (1.0, 0.0)],
                "Main": [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)],
            }[street]

        with patch("backend.geo_engine.get_street_geometry", side_effect=fake_street_geometry), \
             patch("backend.geo_engine.get_coordinates", side_effect=self.fake_get_coordinates):
            _, intersection_center = geo_engine.intersection("First", "Second", "City")
            _, turn_center = geo_engine.street_turn("Main", "Landmark", city="City")

        self.assertAlmostEqual(intersection_center[0], 0.0)
        self.assertAlmostEqual(intersection_center[1], 0.0)
        self.assertIsInstance(turn_center, tuple)

    def test_inside_uses_polygon_boundary(self):
        polygon = [[10.0, 10.0], [10.1, 10.0], [10.1, 10.1], [10.0, 10.0]]
        nominatim_result = [{
            "lon": "10.05",
            "lat": "10.05",
            "geojson": {"type": "Polygon", "coordinates": [polygon]},
            "type": "city",
            "category": "place",
            "importance": 0.5,
        }]

        with patch("backend.geo_engine._resolve_location_context", return_value=("City", None, None)), \
             patch("backend.geo_engine._nominatim_search", return_value=nominatim_result):
            coords, center = geo_engine.inside("City")

        self.assertEqual(coords, polygon)
        self.assertEqual(center, (10.05, 10.05))

    def test_string_step_references_execute_and_export_for_lines(self):
        steps = [
            {"id": 1, "function": "Relative", "inputs": [(0.0, 0.0), "north", "1 km"]},
            {"id": 2, "function": "Relative", "inputs": ["1", "east", "1 km"]},
            {"id": 3, "function": "Between", "inputs": ["Step 1", "RelativeResult2"]},
        ]

        result = geo_engine.execute_steps(steps)
        geojson = geo_engine.make_geojson(result, steps)

        self.assertEqual(set(result), {1, 2, 3})
        inputs = {f["properties"]["step_id"]: f["properties"]["inputs"] for f in geojson["features"]}
        self.assertEqual(inputs[2][0], "1")
        self.assertEqual(inputs[3], ["Step 1", "RelativeResult2"])

    def test_pair_context_reanchors_ambiguous_settlement(self):
        def nominatim_result(name, lon, lat, importance):
            return {
                "display_name": name,
                "lon": str(lon),
                "lat": str(lat),
                "geojson": {"type": "Point", "coordinates": [lon, lat]},
                "type": "village",
                "category": "place",
                "importance": importance,
            }

        far_high = nominatim_result("Высокая Гора, far away", 39.0, 47.0, 0.9)
        local_high = nominatim_result("Высокая Гора, Татарстан", 49.301, 55.913, 0.4)
        derbyshki = nominatim_result("Дербышки, Казань", 49.238, 55.833, 0.5)

        def fake_nominatim(query, country_code=None, auto_featuretype=True,
                           viewbox=None, bounded=False, limit=5):
            if "Высокая Гора" in query:
                return [local_high] if bounded else [far_high]
            if "Дербышки" in query:
                return [derbyshki]
            raise ValueError(query)

        steps = [{
            "id": 1,
            "function": "Between",
            "inputs": ["Высокая Гора", "Дербышки"],
        }]

        with patch("backend.geo_engine._resolve_location_context",
                   side_effect=lambda location: (location, None, None)), \
             patch("backend.geo_engine._nominatim_search", side_effect=fake_nominatim):
            result = geo_engine.execute_steps(steps)

        midpoint = result[1][1]
        self.assertAlmostEqual(midpoint[0], (49.301 + 49.238) / 2)
        self.assertAlmostEqual(midpoint[1], (55.913 + 55.833) / 2)

    def test_unknown_function_raises(self):
        with self.assertRaises(ValueError):
            geo_engine.execute_steps([{"id": 1, "function": "Bogus", "inputs": []}])

    def test_frontend_step_reference_parser_handles_llm_reference_forms(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")

        html = Path("frontend/index.html").read_text(encoding="utf-8")
        start = html.index("function parseStepReference")
        brace_start = html.index("{", start)
        depth = 0
        end = brace_start
        for pos in range(brace_start, len(html)):
            char = html[pos]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = pos + 1
                    break

        function_src = html[start:end]
        script = function_src + """
const cases = [
  [1, 1],
  ["1", 1],
  ["#1", 1],
  ["Step 1", 1],
  ["Result1", 1],
  ["RelativeResult2", 2],
  ["output 3", 3],
  ["Route 66", null],
  ["A", null],
];
for (const [input, expected] of cases) {
  const actual = parseStepReference(input);
  if (actual !== expected) {
    throw new Error(`${input}: expected ${expected}, got ${actual}`);
  }
}
"""
        subprocess.run([node, "--check"], input=script, text=True, check=True)
        subprocess.run([node], input=script, text=True, check=True)

    def test_websocket_single_along_returns_road_geometry(self):
        from fastapi.testclient import TestClient
        import backend.main as main

        steps = [{"id": 1, "function": "Along", "inputs": ["A", "B", "1 km"]}]

        def fake_get_coordinates(place):
            mapping = {"A": (0.0, 0.0), "B": (0.0, 0.02)}
            center = mapping[place]
            return [center[0], center[1]], center, 1.0

        with patch.object(main, "parse", return_value=steps), \
             patch.object(main, "_has_cyrillic", return_value=False), \
             patch.object(main, "get_coordinates", side_effect=fake_get_coordinates), \
             patch.object(geo_engine, "get_coordinates", side_effect=fake_get_coordinates), \
             patch.object(geo_engine, "road_route", return_value=([[0.0, 0.0], [0.0, 0.01]], 1.1)), \
             patch.object(geo_engine, "road_distance", return_value=(1.1, 1.0)):
            client = TestClient(main.app)
            with client.websocket_connect("/ws/parse") as ws:
                ws.send_json({
                    "text": "1 km along road from A toward B",
                    "mode": "fast",
                    "draw_roads": True,
                })
                while True:
                    msg = ws.receive_json()
                    if msg["type"] == "step_result":
                        self.assertEqual(msg.get("road_geometry"), [[0.0, 0.0], [0.0, 0.01]])
                        self.assertEqual(msg.get("road_info", {}).get("road_km"), 1.1)
                    if msg["type"] == "complete":
                        break

    def test_websocket_single_relative_draw_roads_uses_base_location_as_route_start(self):
        from fastapi.testclient import TestClient
        import backend.main as main

        steps = [{"id": 1, "function": "Relative", "inputs": ["Kazan Kremlin", "northeast", "5 km"]}]
        start = (49.106414, 55.798856)
        end = (49.164000, 55.830000)
        route_points = [[start[0], start[1]], [49.132000, 55.814000], [end[0], end[1]]]

        def fake_get_coordinates(place):
            if place != "Kazan Kremlin":
                raise ValueError(place)
            return [start[0], start[1]], start, 1.0

        with patch.object(main, "parse", return_value=steps), \
             patch.object(main, "_has_cyrillic", return_value=False), \
             patch.object(main, "get_coordinates", side_effect=fake_get_coordinates), \
             patch.object(geo_engine, "get_coordinates", side_effect=fake_get_coordinates), \
             patch.object(main, "relative", return_value=(_fake_circle(end, 0.01), end)), \
             patch.object(geo_engine, "road_route", return_value=(route_points, 6.4)) as mocked_route, \
             patch.object(geo_engine, "road_distance", return_value=(6.4, 5.0)) as mocked_distance:
            client = TestClient(main.app)
            with client.websocket_connect("/ws/parse") as ws:
                ws.send_json({
                    "text": "5 km northeast of Kazan Kremlin",
                    "mode": "fast",
                    "draw_roads": True,
                })
                while True:
                    msg = ws.receive_json()
                    if msg["type"] == "step_result":
                        self.assertEqual(msg.get("road_geometry"), route_points)
                        self.assertEqual(msg.get("reference_geometry"), [[start[0], start[1]], [end[0], end[1]]])
                        self.assertEqual(msg.get("road_info", {}).get("road_km"), 6.4)
                    if msg["type"] == "complete":
                        break

        mocked_distance.assert_called_once_with(start[0], start[1], end[0], end[1])
        mocked_route.assert_called_once_with(start[0], start[1], end[0], end[1])

    def test_websocket_between_draw_roads_returns_pair_route_geometry(self):
        from fastapi.testclient import TestClient
        import backend.main as main

        steps = [{"id": 1, "function": "Between", "inputs": ["A", "B"]}]
        point_a = (49.301, 55.913)
        point_b = (49.238, 55.833)
        route_points = [[49.301, 55.913], [49.274, 55.879], [49.238, 55.833]]

        with patch.object(main, "parse", return_value=steps), \
             patch.object(main, "_has_cyrillic", return_value=False), \
             patch.object(main, "resolve_pair_centroids", return_value=(point_a, point_b)), \
             patch.object(geo_engine, "road_route", return_value=(route_points, 8.6)) as mocked_route, \
             patch.object(geo_engine, "road_distance", return_value=(8.6, 7.1)) as mocked_distance:
            client = TestClient(main.app)
            with client.websocket_connect("/ws/parse") as ws:
                ws.send_json({
                    "text": "midpoint between A and B",
                    "mode": "fast",
                    "draw_roads": True,
                })
                while True:
                    msg = ws.receive_json()
                    if msg["type"] == "step_result":
                        self.assertEqual(msg.get("road_geometry"), route_points)
                        self.assertEqual(msg.get("road_info", {}).get("road_km"), 8.6)
                    if msg["type"] == "complete":
                        break

        mocked_distance.assert_called_once_with(point_a[0], point_a[1], point_b[0], point_b[1])
        mocked_route.assert_called_once_with(point_a[0], point_a[1], point_b[0], point_b[1])

    def test_websocket_between_returns_context_reference_line(self):
        from fastapi.testclient import TestClient
        import backend.main as main

        steps = [{
            "id": 1,
            "function": "Between",
            "inputs": ["Высокая Гора", "Дербышки"],
        }]
        high = (49.301, 55.913)
        derbyshki = (49.238, 55.833)

        with patch.object(main, "parse", return_value=steps), \
             patch.object(main, "_has_cyrillic", return_value=False), \
             patch.object(main, "resolve_pair_centroids", return_value=(high, derbyshki)):
            client = TestClient(main.app)
            with client.websocket_connect("/ws/parse") as ws:
                ws.send_json({
                    "text": "Середина между Высокой Горой и Дербышками.",
                    "mode": "fast",
                })
                while True:
                    msg = ws.receive_json()
                    if msg["type"] == "step_result":
                        self.assertEqual(msg.get("reference_geometry"), [[high[0], high[1]], [derbyshki[0], derbyshki[1]]])
                        names = [rp["name"] for rp in msg.get("ref_points", [])]
                        self.assertEqual(names, ["Высокая Гора", "Дербышки"])
                    if msg["type"] == "complete":
                        break

    def test_rest_parse_returns_reference_metadata_for_pair_steps(self):
        from fastapi.testclient import TestClient
        import backend.main as main

        steps = [{
            "id": 1,
            "function": "Between",
            "inputs": ["Высокая Гора", "Дербышки"],
        }]
        high = (49.301, 55.913)
        derbyshki = (49.238, 55.833)
        midpoint = ((high[0] + derbyshki[0]) / 2, (high[1] + derbyshki[1]) / 2)
        step_data = {1: (_fake_circle(midpoint, 0.01), midpoint)}

        with patch.object(main, "parse", return_value=steps), \
             patch.object(main, "_has_cyrillic", return_value=False), \
             patch.object(main, "execute_steps", return_value=step_data), \
             patch.object(main, "resolve_pair_centroids", return_value=(high, derbyshki)):
            client = TestClient(main.app)
            response = client.post("/api/parse", json={"text": "midpoint between A and B", "mode": "fast"})

        self.assertEqual(response.status_code, 200)
        metadata = response.json()["step_metadata"]["1"]
        self.assertEqual(metadata["reference_geometry"], [[high[0], high[1]], [derbyshki[0], derbyshki[1]]])
        self.assertEqual([point["name"] for point in metadata["ref_points"]], ["Высокая Гора", "Дербышки"])


if __name__ == "__main__":
    unittest.main()
