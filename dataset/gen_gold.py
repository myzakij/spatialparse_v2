"""Generate gold_standard.json dataset."""
import math, json

R = 6378.1

def project(lon, lat, bearing_deg, dist_km):
    brng = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(math.sin(lat1)*math.cos(dist_km/R) + math.cos(lat1)*math.sin(dist_km/R)*math.cos(brng))
    lon2 = lon1 + math.atan2(math.sin(brng)*math.sin(dist_km/R)*math.cos(lat1), math.cos(dist_km/R)-math.sin(lat1)*math.sin(lat2))
    return (round(math.degrees(lon2), 5), round(math.degrees(lat2), 5))

def calc_bearing(a, b):
    """Compass bearing from a to b. Points are (lon, lat)."""
    lat1 = math.radians(a[1])
    lat2 = math.radians(b[1])
    dlon = math.radians(b[0] - a[0])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def toward(from_p, toward_p, dist_km):
    """Project from from_p in the direction of toward_p by dist_km."""
    b = calc_bearing(from_p, toward_p)
    return project(from_p[0], from_p[1], b, dist_km)

def mid(a, b):
    return (round((a[0]+b[0])/2, 5), round((a[1]+b[1])/2, 5))

def frac(a, b, r):
    return (round(a[0]+(b[0]-a[0])*r, 5), round(a[1]+(b[1]-a[1])*r, 5))

# Known landmarks: (lon, lat)
P = {
    'eiffel':       (2.2945, 48.8584),
    'kremlin_msk':  (37.6176, 55.7520),
    'sheremetyevo': (37.4146, 55.9726),
    'colosseum':    (12.4924, 41.8902),
    'pantheon_rome':(12.4768, 41.8986),
    'big_ben':      (-0.1246, 51.5007),
    'opera_sydney': (151.2153, -33.8568),
    'central_park': (-73.9654, 40.7829),
    'statue_liberty':(-74.0445, 40.6892),
    'times_square': (-73.9857, 40.7580),
    'tokyo_tower':  (139.7454, 35.6586),
    'kazan_kremlin':(49.1064, 55.7982),
    'burj_khalifa': (55.2744, 25.1972),
    'brandenburg':  (13.3777, 52.5163),
    'arc_triomphe': (2.2950, 48.8738),
    'louvre':       (2.3376, 48.8606),
    'sagrada':      (2.1744, 41.4036),
    'taj_mahal':    (78.0421, 27.1751),
    'pisa_tower':   (10.3966, 43.7230),
    'pyramids':     (31.1342, 29.9792),
    'acropolis':    (23.7257, 37.9715),
    'golden_gate':  (-122.4783, 37.8199),
    'vatican':      (12.4534, 41.9029),
    'buckingham':   (-0.1419, 51.5014),
    'angkor_wat':   (103.8670, 13.4125),
    'stonehenge':   (-1.8262, 51.1789),
    'red_square':   (37.6208, 55.7539),
    'hermitage':    (30.3146, 59.9398),
    'bolshoi':      (37.6186, 55.7601),
    'sparrow_hills':(37.5433, 55.7105),
    'ostankino':    (37.6117, 55.8197),
    'gorky_park':   (37.6010, 55.7312),
    'vdnkh':        (37.6394, 55.8263),
    'tretyakov':    (37.6206, 55.7415),
    'peter_paul':   (30.3163, 59.9502),
    'peterhof':     (29.9087, 59.8861),
    'tokyo_tower':  (139.7454, 35.6586),
    'mount_fuji':   (138.7274, 35.3606),
    'arsk':         (49.8722, 56.0917),
    'kazan':        (49.1064, 55.7982),
    'nizhny_novgorod': (43.9361, 56.2965),
    'vladivostok':  (131.8869, 43.1155),
    'khabarovsk':   (135.0839, 48.4827),
    'sochi':        (39.7233, 43.5992),
    'krasnodar':    (38.9769, 45.0355),
    'novosibirsk':  (82.9346, 55.0084),
    'omsk':         (73.3686, 54.9885),
    'ekaterinburg': (60.6122, 56.8389),
    'chelyabinsk':  (61.4026, 55.1644),
    'murmansk':     (33.0849, 68.9585),
    'arkhangelsk':  (40.5434, 64.5399),
    'irkutsk':      (104.2964, 52.2870),
    'ulan_ude':     (107.5886, 51.8335),
}

dataset = []
idx = 0

# ============ LOCATE (5) ============
for text_ru, place, key in [
    ("Эйфелева башня", "Eiffel Tower, Paris", "eiffel"),
    ("Кремль в Москве", "Kremlin, Moscow", "kremlin_msk"),
    ("Колизей в Риме", "Colosseum, Rome", "colosseum"),
    ("Тадж-Махал", "Taj Mahal", "taj_mahal"),
    ("Казанский Кремль", "Kazan Kremlin", "kazan_kremlin"),
]:
    idx += 1
    dataset.append({
        "id": idx,
        "text": text_ru,
        "expected_steps": [{"id":1, "function":"Locate", "inputs":[place]}],
        "gold_lon": P[key][0],
        "gold_lat": P[key][1],
        "category": "locate",
        "difficulty": "easy",
    })

# ============ RELATIVE (10) ============
rel_cases = [
    ("5 км к югу от Эйфелевой башни", "eiffel", "south", 180, 5, "Eiffel Tower, Paris", "easy"),
    ("10 км к северу от Кремля", "kremlin_msk", "north", 0, 10, "Kremlin, Moscow", "easy"),
    ("3 км к востоку от Колизея", "colosseum", "east", 90, 3, "Colosseum, Rome", "easy"),
    ("7 км к западу от Биг-Бена", "big_ben", "west", 270, 7, "Big Ben, London", "easy"),
    ("15 км к северо-западу от Кремля", "kremlin_msk", "northwest", 315, 15, "Kremlin, Moscow", "medium"),
    ("20 км к юго-востоку от Бурдж-Халифы", "burj_khalifa", "southeast", 135, 20, "Burj Khalifa, Dubai", "medium"),
    ("8 км к северо-востоку от Бранденбургских ворот", "brandenburg", "northeast", 45, 8, "Brandenburg Gate, Berlin", "medium"),
    ("2 км к югу от Казанского Кремля", "kazan_kremlin", "south", 180, 2, "Kazan Kremlin", "easy"),
    ("12 км к юго-западу от Тадж-Махала", "taj_mahal", "southwest", 225, 12, "Taj Mahal", "medium"),
    ("6 км к северу от Акрополя", "acropolis", "north", 0, 6, "Acropolis, Athens", "easy"),
]

for text_ru, key, direction, bearing, dist, place, diff in rel_cases:
    idx += 1
    g = project(P[key][0], P[key][1], bearing, dist)
    dataset.append({
        "id": idx,
        "text": text_ru,
        "expected_steps": [{"id":1, "function":"Relative", "inputs":[place, direction, f"{dist} km"]}],
        "gold_lon": g[0],
        "gold_lat": g[1],
        "category": "relative",
        "difficulty": diff,
    })

# ============ BETWEEN (5) ============
btw_cases = [
    ("Середина пути между Кремлём и Шереметьево", "kremlin_msk", "sheremetyevo", "Kremlin, Moscow", "Sheremetyevo Airport", "easy"),
    ("Средняя точка между Колизеем и Пантеоном в Риме", "colosseum", "pantheon_rome", "Colosseum, Rome", "Pantheon, Rome", "easy"),
    ("Середина между Эйфелевой башней и Лувром", "eiffel", "louvre", "Eiffel Tower, Paris", "Louvre, Paris", "easy"),
    ("Средняя точка между Биг-Беном и Букингемским дворцом", "big_ben", "buckingham", "Big Ben, London", "Buckingham Palace, London", "easy"),
    ("Середина пути между пирамидами Гизы и Акрополем", "pyramids", "acropolis", "Pyramids of Giza", "Acropolis, Athens", "medium"),
]

for text_ru, k1, k2, p1, p2, diff in btw_cases:
    idx += 1
    g = mid(P[k1], P[k2])
    dataset.append({
        "id": idx,
        "text": text_ru,
        "expected_steps": [{"id":1, "function":"Between", "inputs":[p1, p2]}],
        "gold_lon": g[0],
        "gold_lat": g[1],
        "category": "between",
        "difficulty": diff,
    })

# ============ FRACTION (5) ============
frac_cases = [
    ("Четверть пути от Статуи Свободы до Таймс-сквер", "statue_liberty", "times_square", 0.25, "Statue of Liberty", "Times Square, New York", "medium"),
    ("Три четверти пути от Эйфелевой башни до Триумфальной арки", "eiffel", "arc_triomphe", 0.75, "Eiffel Tower, Paris", "Arc de Triomphe, Paris", "medium"),
    ("Треть пути от Кремля до Останкинской башни", "kremlin_msk", "ostankino", 0.333, "Kremlin, Moscow", "Ostankino Tower, Moscow", "medium"),
    ("Половина пути от Эрмитажа до Петергофа", "hermitage", "peterhof", 0.5, "Hermitage, Saint Petersburg", "Peterhof", "medium"),
    ("Две трети пути от Токийской башни до горы Фудзи", "tokyo_tower", "mount_fuji", 0.667, "Tokyo Tower", "Mount Fuji", "hard"),
]

for text_ru, k1, k2, ratio, p1, p2, diff in frac_cases:
    idx += 1
    g = frac(P[k1], P[k2], ratio)
    dataset.append({
        "id": idx,
        "text": text_ru,
        "expected_steps": [{"id":1, "function":"Fraction", "inputs":[p1, p2, ratio]}],
        "gold_lon": g[0],
        "gold_lat": g[1],
        "category": "fraction",
        "difficulty": diff,
    })

# ============ AZIMUTH (5) ============
az_cases = [
    ("8 км по азимуту 120 градусов от Сиднейского оперного театра", "opera_sydney", 120, 8, "Sydney Opera House", "easy"),
    ("10 км по азимуту 45 градусов от Кремля", "kremlin_msk", 45, 10, "Kremlin, Moscow", "easy"),
    ("5 км по азимуту 200 градусов от Бурдж-Халифы", "burj_khalifa", 200, 5, "Burj Khalifa, Dubai", "medium"),
    ("15 км по азимуту 330 градусов от пирамид Гизы", "pyramids", 330, 15, "Pyramids of Giza", "medium"),
    ("3 км по азимуту 90 градусов от Пизанской башни", "pisa_tower", 90, 3, "Leaning Tower of Pisa", "easy"),
]

for text_ru, key, angle, dist, place, diff in az_cases:
    idx += 1
    g = project(P[key][0], P[key][1], angle, dist)
    dataset.append({
        "id": idx,
        "text": text_ru,
        "expected_steps": [{"id":1, "function":"Azimuth", "inputs":[place, angle, f"{dist} km"]}],
        "gold_lon": g[0],
        "gold_lat": g[1],
        "category": "azimuth",
        "difficulty": diff,
    })

# ============ TOWARD (7) ============
toward_cases = [
    ("20 километров в сторону Казани от Арска", "arsk", "kazan", 20,
     "Arsk, Tatarstan", "Kazan", "medium"),
    ("50 км от Москвы в сторону Нижнего Новгорода", "kremlin_msk", "nizhny_novgorod", 50,
     "Moscow", "Nizhny Novgorod", "medium"),
    ("30 км от Сочи в сторону Краснодара", "sochi", "krasnodar", 30,
     "Sochi", "Krasnodar", "medium"),
    ("100 км от Новосибирска в сторону Омска", "novosibirsk", "omsk", 100,
     "Novosibirsk", "Omsk", "hard"),
    ("40 км от Екатеринбурга в сторону Челябинска", "ekaterinburg", "chelyabinsk", 40,
     "Yekaterinburg", "Chelyabinsk", "medium"),
    ("80 км от Мурманска в направлении Архангельска", "murmansk", "arkhangelsk", 80,
     "Murmansk", "Arkhangelsk", "hard"),
    ("60 км от Иркутска в сторону Улан-Удэ", "irkutsk", "ulan_ude", 60,
     "Irkutsk", "Ulan-Ude", "medium"),
]

for text_ru, k_from, k_toward, dist, p_from, p_toward, diff in toward_cases:
    idx += 1
    g = toward(P[k_from], P[k_toward], dist)
    dataset.append({
        "id": idx,
        "text": text_ru,
        "expected_steps": [{"id":1, "function":"Toward", "inputs":[p_from, p_toward, f"{dist} km"]}],
        "gold_lon": g[0],
        "gold_lat": g[1],
        "category": "toward",
        "difficulty": diff,
    })

# ============ ALONG (5) ============
# Gold coords computed via OSRM road routing for accurate comparison.
import requests as _req

def _along_road(from_pt, toward_pt, dist_km):
    """Walk along OSRM route for dist_km. Returns (lon, lat) or falls back to straight line."""
    try:
        url = (f"https://router.project-osrm.org/route/v1/driving/"
               f"{from_pt[0]},{from_pt[1]};{toward_pt[0]},{toward_pt[1]}"
               f"?overview=full&geometries=geojson")
        resp = _req.get(url, timeout=15)
        data = resp.json()
        if data.get("code") == "Ok" and data.get("routes"):
            coords = data["routes"][0]["geometry"]["coordinates"]
            walked = 0.0
            for i in range(1, len(coords)):
                p0, p1 = coords[i-1], coords[i]
                # Haversine between consecutive points
                import math as _m
                lon1, lat1, lon2, lat2 = map(_m.radians, [p0[0], p0[1], p1[0], p1[1]])
                dlat = lat2 - lat1; dlon = lon2 - lon1
                a = _m.sin(dlat/2)**2 + _m.cos(lat1)*_m.cos(lat2)*_m.sin(dlon/2)**2
                seg = 6371 * 2 * _m.asin(_m.sqrt(a))
                if walked + seg >= dist_km:
                    ratio = (dist_km - walked) / seg if seg > 0 else 0
                    return (round(p0[0] + (p1[0]-p0[0]) * ratio, 5),
                            round(p0[1] + (p1[1]-p0[1]) * ratio, 5))
                walked += seg
            # If route is shorter than requested distance, return last point
            return (round(coords[-1][0], 5), round(coords[-1][1], 5))
    except Exception as e:
        print(f"  OSRM failed for Along gold: {e}, using straight line")
    return toward(from_pt, toward_pt, dist_km)

along_cases = [
    ("20 км от Арска вдоль трассы М7 в сторону Казани", "arsk", "kazan", 20,
     "Arsk, Tatarstan", "Kazan", "medium"),
    ("50 км от Москвы по дороге в сторону Нижнего Новгорода", "kremlin_msk", "nizhny_novgorod", 50,
     "Moscow", "Nizhny Novgorod", "hard"),
    ("30 км от Сочи вдоль шоссе в сторону Краснодара", "sochi", "krasnodar", 30,
     "Sochi", "Krasnodar", "medium"),
    ("40 км от Екатеринбурга по трассе в сторону Челябинска", "ekaterinburg", "chelyabinsk", 40,
     "Yekaterinburg", "Chelyabinsk", "medium"),
    ("60 км от Иркутска вдоль дороги в сторону Улан-Удэ", "irkutsk", "ulan_ude", 60,
     "Irkutsk", "Ulan-Ude", "hard"),
]

for text_ru, k_from, k_toward, dist, p_from, p_toward, diff in along_cases:
    idx += 1
    g = _along_road(P[k_from], P[k_toward], dist)  # OSRM-based gold
    print(f"  Along: {text_ru[:40]}... -> ({g[0]}, {g[1]})")
    dataset.append({
        "id": idx,
        "text": text_ru,
        "expected_steps": [{"id":1, "function":"Along", "inputs":[p_from, p_toward, f"{dist} km"]}],
        "gold_lon": g[0],
        "gold_lat": g[1],
        "category": "along",
        "difficulty": diff,
    })

# ============ INTERSECTION (5) ============
# Gold coords: known intersection points (manually verified)
intersection_data = [
    ("Пересечение улицы Баумана и Профсоюзной в Казани",
     "Bauman Street", "Profsoyuznaya Street", "Kazan",
     49.1154, 55.7893, "medium"),
    ("Перекрёсток Тверской и Бульварного кольца в Москве",
     "Tverskaya Street", "Boulevard Ring", "Moscow",
     37.6059, 55.7633, "medium"),
    ("Пересечение Невского проспекта и Садовой улицы в Петербурге",
     "Nevsky Prospect", "Sadovaya Street", "Saint Petersburg",
     30.3339, 59.9293, "medium"),
    ("Перекрёсток Oxford Street и Regent Street в Лондоне",
     "Oxford Street", "Regent Street", "London",
     -0.1410, 51.5152, "medium"),
    ("Пересечение Broadway и 7th Avenue в Нью-Йорке",
     "Broadway", "7th Avenue", "New York",
     -73.9857, 40.7580, "medium"),
]

for text_ru, s1, s2, city, gold_lon, gold_lat, diff in intersection_data:
    idx += 1
    dataset.append({
        "id": idx,
        "text": text_ru,
        "expected_steps": [{"id":1, "function":"Intersection", "inputs":[s1, s2, city]}],
        "gold_lon": gold_lon,
        "gold_lat": gold_lat,
        "category": "intersection",
        "difficulty": diff,
    })

# ============ CHAINS (10) ============

# Chain 1: Relative + Between
s1 = project(P["kremlin_msk"][0], P["kremlin_msk"][1], 315, 15)
g = mid(s1, P["sheremetyevo"])
idx += 1
dataset.append({
    "id": idx,
    "text": "15 км к северо-западу от Кремля, затем середина пути до Шереметьево",
    "expected_steps": [
        {"id":1, "function":"Relative", "inputs":["Kremlin, Moscow", "northwest", "15 km"]},
        {"id":2, "function":"Between", "inputs":[1, "Sheremetyevo Airport"]},
    ],
    "gold_lon": g[0], "gold_lat": g[1],
    "category": "chain", "difficulty": "hard",
})

# Chain 2: Relative + Relative
s1 = project(P["big_ben"][0], P["big_ben"][1], 90, 6)
g = project(s1[0], s1[1], 180, 4)
idx += 1
dataset.append({
    "id": idx,
    "text": "6 км к востоку от Биг-Бена, затем 4 км к югу",
    "expected_steps": [
        {"id":1, "function":"Relative", "inputs":["Big Ben, London", "east", "6 km"]},
        {"id":2, "function":"Relative", "inputs":[1, "south", "4 km"]},
    ],
    "gold_lon": g[0], "gold_lat": g[1],
    "category": "chain", "difficulty": "hard",
})

# Chain 3: Locate + Relative
g = project(P["eiffel"][0], P["eiffel"][1], 0, 3)
idx += 1
dataset.append({
    "id": idx,
    "text": "Найди Эйфелеву башню, затем 3 км к северу от неё",
    "expected_steps": [
        {"id":1, "function":"Locate", "inputs":["Eiffel Tower, Paris"]},
        {"id":2, "function":"Relative", "inputs":[1, "north", "3 km"]},
    ],
    "gold_lon": g[0], "gold_lat": g[1],
    "category": "chain", "difficulty": "medium",
})

# Chain 4: Between + Relative
s1 = mid(P["colosseum"], P["vatican"])
g = project(s1[0], s1[1], 180, 2)
idx += 1
dataset.append({
    "id": idx,
    "text": "Середина между Колизеем и Ватиканом, затем 2 км к югу",
    "expected_steps": [
        {"id":1, "function":"Between", "inputs":["Colosseum, Rome", "Vatican"]},
        {"id":2, "function":"Relative", "inputs":[1, "south", "2 km"]},
    ],
    "gold_lon": g[0], "gold_lat": g[1],
    "category": "chain", "difficulty": "hard",
})

# Chain 5: Relative + Between (Moscow)
s1 = project(P["red_square"][0], P["red_square"][1], 90, 5)
g = mid(s1, P["bolshoi"])
idx += 1
dataset.append({
    "id": idx,
    "text": "5 км к востоку от Красной площади, затем середина пути до Большого театра",
    "expected_steps": [
        {"id":1, "function":"Relative", "inputs":["Red Square, Moscow", "east", "5 km"]},
        {"id":2, "function":"Between", "inputs":[1, "Bolshoi Theatre, Moscow"]},
    ],
    "gold_lon": g[0], "gold_lat": g[1],
    "category": "chain", "difficulty": "hard",
})

# Chain 6: Azimuth + Between
s1 = project(P["brandenburg"][0], P["brandenburg"][1], 60, 10)
g = mid(s1, P["brandenburg"])
idx += 1
dataset.append({
    "id": idx,
    "text": "10 км по азимуту 60 градусов от Бранденбургских ворот, затем середина пути обратно до ворот",
    "expected_steps": [
        {"id":1, "function":"Azimuth", "inputs":["Brandenburg Gate, Berlin", 60, "10 km"]},
        {"id":2, "function":"Between", "inputs":[1, "Brandenburg Gate, Berlin"]},
    ],
    "gold_lon": g[0], "gold_lat": g[1],
    "category": "chain", "difficulty": "hard",
})

# Chain 7: Relative x3
s1 = project(P["kazan_kremlin"][0], P["kazan_kremlin"][1], 0, 5)
s2 = project(s1[0], s1[1], 90, 3)
g = project(s2[0], s2[1], 180, 2)
idx += 1
dataset.append({
    "id": idx,
    "text": "5 км к северу от Казанского Кремля, затем 3 км к востоку, затем 2 км к югу",
    "expected_steps": [
        {"id":1, "function":"Relative", "inputs":["Kazan Kremlin", "north", "5 km"]},
        {"id":2, "function":"Relative", "inputs":[1, "east", "3 km"]},
        {"id":3, "function":"Relative", "inputs":[2, "south", "2 km"]},
    ],
    "gold_lon": g[0], "gold_lat": g[1],
    "category": "chain", "difficulty": "hard",
})

# Chain 8: Fraction + Relative
s1 = frac(P["hermitage"], P["peter_paul"], 0.5)
g = project(s1[0], s1[1], 90, 1)
idx += 1
dataset.append({
    "id": idx,
    "text": "Половина пути от Эрмитажа до Петропавловской крепости, затем 1 км к востоку",
    "expected_steps": [
        {"id":1, "function":"Fraction", "inputs":["Hermitage, Saint Petersburg", "Peter and Paul Fortress, Saint Petersburg", 0.5]},
        {"id":2, "function":"Relative", "inputs":[1, "east", "1 km"]},
    ],
    "gold_lon": g[0], "gold_lat": g[1],
    "category": "chain", "difficulty": "hard",
})

# Chain 9: Relative + Fraction
s1 = project(P["eiffel"][0], P["eiffel"][1], 90, 4)
g = frac(s1, P["louvre"], 0.5)
idx += 1
dataset.append({
    "id": idx,
    "text": "4 км к востоку от Эйфелевой башни, затем половина пути оттуда до Лувра",
    "expected_steps": [
        {"id":1, "function":"Relative", "inputs":["Eiffel Tower, Paris", "east", "4 km"]},
        {"id":2, "function":"Fraction", "inputs":[1, "Louvre, Paris", 0.5]},
    ],
    "gold_lon": g[0], "gold_lat": g[1],
    "category": "chain", "difficulty": "hard",
})

# Chain 10: Between + Between
s1 = mid(P["kremlin_msk"], P["sparrow_hills"])
g = mid(s1, P["gorky_park"])
idx += 1
dataset.append({
    "id": idx,
    "text": "Середина между Кремлём и Воробьёвыми горами, затем середина оттуда до Парка Горького",
    "expected_steps": [
        {"id":1, "function":"Between", "inputs":["Kremlin, Moscow", "Sparrow Hills, Moscow"]},
        {"id":2, "function":"Between", "inputs":[1, "Gorky Park, Moscow"]},
    ],
    "gold_lon": g[0], "gold_lat": g[1],
    "category": "chain", "difficulty": "hard",
})

# Chain 11: Toward + Between
s1 = toward(P["arsk"], P["kazan"], 20)
g = mid(s1, P["kazan"])
idx += 1
dataset.append({
    "id": idx,
    "text": "20 км от Арска в сторону Казани, затем середина пути оттуда до Казани",
    "expected_steps": [
        {"id":1, "function":"Toward", "inputs":["Arsk, Tatarstan", "Kazan", "20 km"]},
        {"id":2, "function":"Between", "inputs":[1, "Kazan"]},
    ],
    "gold_lon": g[0], "gold_lat": g[1],
    "category": "chain", "difficulty": "hard",
})

# Chain 12: Toward + Relative
s1 = toward(P["sochi"], P["krasnodar"], 30)
g = project(s1[0], s1[1], 90, 5)
idx += 1
dataset.append({
    "id": idx,
    "text": "30 км от Сочи в сторону Краснодара, затем 5 км к востоку",
    "expected_steps": [
        {"id":1, "function":"Toward", "inputs":["Sochi", "Krasnodar", "30 km"]},
        {"id":2, "function":"Relative", "inputs":[1, "east", "5 km"]},
    ],
    "gold_lon": g[0], "gold_lat": g[1],
    "category": "chain", "difficulty": "hard",
})

# Chain 13: Relative + Toward
s1 = project(P["kremlin_msk"][0], P["kremlin_msk"][1], 0, 10)
g = toward(s1, P["sheremetyevo"], 5)
idx += 1
dataset.append({
    "id": idx,
    "text": "10 км к северу от Кремля, затем 5 км в сторону Шереметьево",
    "expected_steps": [
        {"id":1, "function":"Relative", "inputs":["Kremlin, Moscow", "north", "10 km"]},
        {"id":2, "function":"Toward", "inputs":[1, "Sheremetyevo Airport", "5 km"]},
    ],
    "gold_lon": g[0], "gold_lat": g[1],
    "category": "chain", "difficulty": "hard",
})

# ============ SAVE ============
with open("dataset/gold_standard.json", "w", encoding="utf-8") as f:
    json.dump(dataset, f, ensure_ascii=False, indent=2)

print(f"Done: {len(dataset)} examples")

# Summary
from collections import Counter
cats = Counter(d["category"] for d in dataset)
for cat, cnt in sorted(cats.items()):
    print(f"  {cat}: {cnt}")
