"""Single LLM call: natural language text -> positioning step chain.

Improvements:
- Few-shot examples selected by query type
- LLM translation cache
- Result verification
"""

import json
import re
import logging

from backend.config import get_openai_client, DEFAULT_MODEL

logger = logging.getLogger(__name__)

# ── Base prompt (function definitions + rules) ────────────

_BASE_PROMPT = (
    "You are an experienced geographer. Convert natural language geographic descriptions "
    "into a MINIMAL sequence of positioning functions.\n\n"
    "Available functions:\n"
    "1. Locate(place) — look up a place. Input: place name string.\n"
    "2. Relative(location, direction, distance) — offset from a location.\n"
    "   - location: place name (string) or previous step id (integer)\n"
    "   - direction: ONLY one of: north, south, east, west, northeast, northwest, southeast, southwest\n"
    "   - distance: e.g. '5 km'. Default '1 km'.\n"
    "   - NEVER use a place name as direction. If direction is 'toward CityName', use Toward() or Along() instead.\n"
    "3. Between(location1, location2) — midpoint between two locations.\n"
    "4. Fraction(location1, location2, ratio) — fractional position (0.0=loc1, 1.0=loc2).\n"
    "   - 'one-fourth from A to B' → Fraction('A', 'B', 0.25)\n"
    "5. Azimuth(location, angle, distance) — specific compass bearing.\n"
    "   - angle: degrees (0=N, 90=E, 180=S, 270=W)\n"
    "6. Toward(from_place, toward_place, distance) — move FROM a place TOWARD another place by a given distance.\n"
    "   - from_place: starting location (string or step id)\n"
    "   - toward_place: direction target (string or step id)\n"
    "   - distance: e.g. '20 km'\n"
    "   - Use when the text says 'X km in the direction of B from A' or 'X km from A toward B'.\n"
    "   - Unlike Relative, the bearing is computed automatically from from_place to toward_place.\n"
    "   - IMPORTANT: if the direction is expressed as a place name (e.g. 'toward Kazan'), use Toward, NOT Relative.\n"
    "7. Along(from_place, toward_place, distance) — move along the ROAD from one place toward another.\n"
    "   - from_place: starting location (string or step id)\n"
    "   - toward_place: direction target (string or step id)\n"
    "   - distance: e.g. '20 km'\n"
    "   - Unlike Toward (straight line), this follows the actual road.\n"
    "   - Use when the text mentions a specific road/highway (e.g. 'along M7', 'by road', 'along the highway').\n"
    "   - IMPORTANT: if the text mentions a road name or 'along the road/highway', use Along, NOT Relative or Toward.\n"
    "8. Intersection(street1, street2, city) — find where two streets cross.\n"
    "   - street1, street2: street names (strings)\n"
    "   - city: optional city context (string or null)\n"
    "   - Use when the text says 'intersection of X and Y', 'where X meets Y', 'corner of X and Y'.\n"
    "9. Near(place, qualifier) — fuzzy proximity: 'near', 'nearby', 'in the vicinity of'.\n"
    "   - place: place name (string)\n"
    "   - qualifier: 'adjacent' (рядом, у, возле) | 'close' (недалеко, nearby) | 'vicinity' (в окрестностях) | 'region' (в регионе)\n"
    "   - Use when NO specific distance or direction is given, only vague proximity.\n"
    "   - Do NOT use Near if a specific distance is given (use Relative instead).\n"
    "10. Inside(place) — return the boundary/area of a place itself.\n"
    "   - place: place name (string)\n"
    "   - Use for 'within city limits', 'inside the park', 'in the territory of'.\n"
    "11. StreetTurn(street, toward_place, from_place, city) — find the point on a street where you turn toward a landmark.\n"
    "   - street: street name (string)\n"
    "   - toward_place: the place you turn towards (string)\n"
    "   - from_place: optional, where you come from (string or null)\n"
    "   - city: optional, city context (string or null)\n"
    "   - Use when the description mentions moving along a street and turning toward a place.\n\n"
    "RULES:\n"
    "- Use MINIMUM steps. Prefer 1-2.\n"
    "- Use Near() for vague proximity phrases ('near X', 'in the vicinity of X') when no distance is specified.\n"
    "- All directions in English.\n"
    "- Reference previous steps by INTEGER id, NOT strings like 'step1'.\n"
    "- If text is in Russian/other language, translate place names to standard English form.\n"
    "- IMPORTANT: When multiple places are mentioned together, add geographic context to AMBIGUOUS names.\n"
    "  For example, 'from Burwood to Sydney Town Hall' — Burwood is near Sydney, so output 'Burwood, Sydney'\n"
    "  not just 'Burwood'. This prevents geocoding to the wrong city/country.\n"
    "  Only add context if the name is ambiguous (common name, exists in multiple countries).\n\n"
    "Output JSON between <<<JSON>>> and <<<END>>>.\n"
)

# ── Few-shot examples by query type ──────────────────────

_EXAMPLES = {
    'relative': [
        ('5 km south of the Eiffel Tower.',
         '[{"id": 1, "function": "Relative", "inputs": ["Eiffel Tower", "south", "5 km"]}]'),
        ('3 km northeast of Central Park in New York.',
         '[{"id": 1, "function": "Relative", "inputs": ["Central Park, New York", "northeast", "3 km"]}]'),
    ],
    'between': [
        ('Find the midpoint between the Colosseum and the Pantheon in Rome.',
         '[{"id": 1, "function": "Between", "inputs": ["Colosseum, Rome", "Pantheon, Rome"]}]'),
        ('Midpoint between Paris and London, then midpoint of that and Paris.',
         '[{"id": 1, "function": "Between", "inputs": ["Paris", "London"]}, '
         '{"id": 2, "function": "Between", "inputs": [1, "Paris"]}]'),
    ],
    'fraction': [
        ('One-quarter of the way from Burwood to Sydney Town Hall.',
         '[{"id": 1, "function": "Fraction", "inputs": ["Burwood, Sydney", "Sydney Town Hall", 0.25]}]'),
        ('Three-quarters from the Statue of Liberty to Times Square.',
         '[{"id": 1, "function": "Fraction", "inputs": ["Statue of Liberty", "Times Square, New York", 0.75]}]'),
    ],
    'azimuth': [
        ('8 km at bearing 120 degrees from Sydney Opera House.',
         '[{"id": 1, "function": "Azimuth", "inputs": ["Sydney Opera House", 120, "8 km"]}]'),
        ('Navigate 4 km at 36 degrees from Jasper, then midpoint with Banff.',
         '[{"id": 1, "function": "Azimuth", "inputs": ["Jasper", 36, "4 km"]}, '
         '{"id": 2, "function": "Between", "inputs": ["Banff", 1]}]'),
    ],
    'toward': [
        ('The place is 20 km from Arsk in the direction of Kazan.',
         '[{"id": 1, "function": "Toward", "inputs": ["Arsk, Tatarstan", "Kazan", "20 km"]}]'),
        ('30 km from Sydney toward Canberra.',
         '[{"id": 1, "function": "Toward", "inputs": ["Sydney", "Canberra", "30 km"]}]'),
    ],
    'along': [
        ('20 km from Arsk along the M7 highway toward Kazan.',
         '[{"id": 1, "function": "Along", "inputs": ["Arsk, Tatarstan", "Kazan", "20 km"]}]'),
        ('50 km from Moscow along the road to Nizhny Novgorod.',
         '[{"id": 1, "function": "Along", "inputs": ["Moscow", "Nizhny Novgorod", "50 km"]}]'),
    ],
    'near': [
        ('Somewhere near the Bolshoi Theatre.',
         '[{"id": 1, "function": "Near", "inputs": ["Bolshoi Theatre, Moscow", "adjacent"]}]'),
        ('In the vicinity of Kazan, near the Volga river.',
         '[{"id": 1, "function": "Near", "inputs": ["Kazan", "vicinity"]}]'),
    ],
    'inside': [
        ('Within the city limits of Kazan.',
         '[{"id": 1, "function": "Inside", "inputs": ["Kazan"]}]'),
        ('Inside Gorky Park in Moscow.',
         '[{"id": 1, "function": "Inside", "inputs": ["Gorky Park, Moscow"]}]'),
    ],
    'intersection': [
        ('The intersection of Bauman Street and Profsoyuznaya Street in Kazan.',
         '[{"id": 1, "function": "Intersection", "inputs": ["Bauman Street", "Profsoyuznaya Street", "Kazan"]}]'),
        ('Where Oxford Street meets Regent Street in London.',
         '[{"id": 1, "function": "Intersection", "inputs": ["Oxford Street", "Regent Street", "London"]}]'),
    ],
    'street': [
        ('The place is on Vishnevsky Street heading toward Korston, turning toward Sovetskaya Square in Kazan.',
         '[{"id": 1, "function": "StreetTurn", "inputs": ["Vishnevsky Street", "Sovetskaya Square, Kazan", "Korston, Kazan", "Kazan"]}]'),
        ('Walk along Oxford Street toward Marble Arch and turn toward Hyde Park.',
         '[{"id": 1, "function": "StreetTurn", "inputs": ["Oxford Street", "Hyde Park, London", "Marble Arch, London", "London"]}]'),
    ],
    'chain': [
        ('15 km NW of Kremlin, then midpoint to Sheremetyevo.',
         '[{"id": 1, "function": "Relative", "inputs": ["Kremlin, Moscow", "northwest", "15 km"]}, '
         '{"id": 2, "function": "Between", "inputs": [1, "Sheremetyevo Airport"]}]'),
        ('6 km east of Big Ben, then 4 km south.',
         '[{"id": 1, "function": "Relative", "inputs": ["Big Ben, London", "east", "6 km"]}, '
         '{"id": 2, "function": "Relative", "inputs": [1, "south", "4 km"]}]'),
    ],
}

# Keywords to detect query type
_TYPE_PATTERNS = {
    'near': [r'\bnear\b', r'\bnearby\b', r'рядом', r'возле', r'поблизости', r'недалеко',
             r'неподалёку', r'в\s+окрестност', r'in\s+the\s+vicinity', r'close\s+to',
             r'в\s+район[ее]'],
    'inside': [r'within\s+(the\s+)?(city|limits|bounds|territory|area)', r'inside\s+',
               r'в\s+черте', r'внутри', r'на\s+территории', r'в\s+пределах'],
    'intersection': [r'intersection', r'пересечени', r'перекрест', r'corner\s+of',
                     r'where\s+\w+\s+meets', r'на\s+углу', r'crosses'],
    'along': [r'along\s+the\s+(?:road|highway|route|motorway)', r'вдоль\s+(?:трассы|дороги|шоссе)',
              r'по\s+(?:трассе|дороге|шоссе)', r'along\s+[mMмМ]\d', r'по\s+[mMмМ]\d',
              r'у\s+дороги', r'by\s+(?:the\s+)?road'],
    'street': [r'street', r'avenue', r'road', r'boulevard', r'ulits', r'turn\s+toward',
               r'heading\s+toward', r'walk\s+along', r'drive\s+along'],
    'toward': [r'in\s+the\s+direction\s+of', r'в\s+сторону', r'по\s+направлению\s+к',
               r'from\s+\w+\s+toward', r'от\s+\w+\s+в\s+сторону'],
    'fraction': [r'quarter', r'third', r'half.*way', r'three.quarter', r'one.fourth', r'fraction', r'\d/\d'],
    'azimuth': [r'bearing', r'azimuth', r'\d+\s*°', r'\d+\s*degree'],
    'between': [r'midpoint', r'between', r'halfway'],
    'chain': [r'then', r'from\s+(?:that|this|there)', r'proceed', r'continue'],
    'relative': [r'north|south|east|west|northeast|northwest|southeast|southwest'],
}

_STEP_ARITY = {
    "Locate": (1, 1),
    "Location": (1, 1),
    "Relative": (3, 3),
    "Between": (2, 2),
    "Fraction": (3, 3),
    "Azimuth": (3, 3),
    "Toward": (3, 3),
    "Along": (3, 3),
    "Intersection": (2, 3),
    "Near": (1, 2),
    "Inside": (1, 1),
    "StreetTurn": (2, 4),
}

_REFERENCE_INPUTS = {
    "Relative": {0},
    "Between": {0, 1},
    "Fraction": {0, 1},
    "Azimuth": {0},
    "Toward": {0, 1},
    "Along": {0, 1},
}

_DIRECTIONS = {
    "north", "south", "east", "west",
    "northeast", "northwest", "southeast", "southwest",
    "north east", "north west", "south east", "south west",
    "north-east", "north-west", "south-east", "south-west",
}

_DIRECTION_ALIASES = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "ne": "northeast",
    "nw": "northwest",
    "se": "southeast",
    "sw": "southwest",
}


def _classify_query(text):
    """Classify query to select best few-shot examples."""
    text_lower = text.lower()
    scores = {}
    for qtype, patterns in _TYPE_PATTERNS.items():
        scores[qtype] = sum(1 for p in patterns if re.search(p, text_lower))

    # Chain detection: if has direction AND "then"/"between"
    if scores.get('chain', 0) > 0 and (scores.get('relative', 0) > 0 or scores.get('between', 0) > 0):
        return 'chain'

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'relative'


def _build_prompt(text):
    """Build prompt with type-specific few-shot examples."""
    qtype = _classify_query(text)
    examples = _EXAMPLES.get(qtype, _EXAMPLES['relative'])

    prompt = _BASE_PROMPT + "Examples:\n"
    for q, a in examples:
        prompt += f'\nInput: "{q}"\n<<<JSON>>>\n{a}\n<<<END>>>\n'

    logger.debug("Query classified as '%s', using %d examples", qtype, len(examples))
    return prompt


# ── Core LLM functions ───────────────────────────────────

def _validate_steps(steps):
    """Validate and normalize LLM-produced step JSON before execution."""
    if not isinstance(steps, list) or not steps:
        raise ValueError("LLM output must be a non-empty JSON array")

    normalized = []
    seen_ids = set()

    for index, raw_step in enumerate(steps, start=1):
        if not isinstance(raw_step, dict):
            raise ValueError(f"Step {index} must be an object")

        sid = raw_step.get("id", index)
        try:
            sid = int(sid)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Step {index} has invalid id") from exc

        if sid in seen_ids:
            raise ValueError(f"Duplicate step id: {sid}")
        if sid <= 0:
            raise ValueError(f"Step id must be positive: {sid}")

        func = raw_step.get("function")
        if func not in _STEP_ARITY:
            raise ValueError(f"Unknown function: {func}")

        inputs = raw_step.get("inputs", [])
        if not isinstance(inputs, list):
            raise ValueError(f"Step {sid} inputs must be a list")

        min_args, max_args = _STEP_ARITY[func]
        if not min_args <= len(inputs) <= max_args:
            raise ValueError(
                f"{func} expects {min_args}-{max_args} inputs, got {len(inputs)}"
            )

        if func == "Relative":
            direction = str(inputs[1]).lower().strip()
            direction = _DIRECTION_ALIASES.get(direction, direction)
            if direction not in _DIRECTIONS:
                raise ValueError(f"Unknown direction for Relative: {inputs[1]}")
            inputs[1] = direction

        for pos in _REFERENCE_INPUTS.get(func, set()):
            value = inputs[pos]
            if isinstance(value, int) and value not in seen_ids:
                raise ValueError(f"Step {sid} references unknown previous step {value}")

        normalized.append({"id": sid, "function": func, "inputs": inputs})
        seen_ids.add(sid)

    return normalized


def _parse_steps(llm_output):
    m = re.search(r'<<<JSON>>>\s*(.*?)\s*<<<END>>>', llm_output, re.DOTALL)
    if m:
        return _validate_steps(json.loads(m.group(1)))
    m = re.search(r'(\[\s*\{.*?\}\s*\])', llm_output, re.DOTALL)
    if m:
        return _validate_steps(json.loads(m.group(1)))
    return None


def _call_llm(text, system_prompt=None):
    try:
        if system_prompt is None:
            system_prompt = _build_prompt(text)
        client = get_openai_client()
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        )
        result = resp.choices[0].message.content
        logger.debug("LLM response: %s", result[:200])
        steps = _parse_steps(result)
        return steps if steps else None
    except json.JSONDecodeError as e:
        logger.error("JSON parse error: %s", e)
    except Exception as e:
        logger.error("LLM error: %s", e)
    return None


def _simplify_text(text):
    try:
        client = get_openai_client()
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": (
                    "Simplify the geographic description to ONE precise spatial instruction. "
                    "Keep only: place name + direction + distance. "
                    "Output ONLY the simplified text."
                )},
                {"role": "user", "content": text},
            ],
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return text


# ── Translation with cache ───────────────────────────────

def _has_cyrillic(text):
    return bool(re.search('[а-яА-ЯёЁ]', text))


def _translate_to_english(text):
    """Translate Russian text to English. Cached in SQLite."""
    from backend.geo_engine import llm_cache_get, llm_cache_set

    cache_key = f"translate:{text}"
    cached = llm_cache_get(cache_key)
    if cached:
        logger.debug("Translation cache hit")
        return cached

    try:
        client = get_openai_client()
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": (
                    "Translate the geographic text from Russian to English.\n"
                    "Rules:\n"
                    "- Use standard English names (Казань → Kazan, Москва → Moscow)\n"
                    "- Translate directions (к северу → north, к юго-западу → southwest)\n"
                    "- Convert units (километров → km)\n"
                    "- For ambiguous landmarks add city context\n"
                    "- Output ONLY the translated text"
                )},
                {"role": "user", "content": text},
            ],
        )
        translated = resp.choices[0].message.content.strip()
        logger.info("Translated: '%s' -> '%s'", text[:50], translated[:50])
        llm_cache_set(cache_key, translated)
        return translated
    except Exception:
        return text


# ── Verification ─────────────────────────────────────────

def _verify_result(text, steps, final_centroid):
    """Ask LLM if the result makes geographic sense. Returns True if plausible."""
    try:
        steps_desc = []
        for s in steps:
            func = s['function']
            inputs = ', '.join(str(i) for i in s['inputs'])
            steps_desc.append(f"  Step {s['id']}: {func}({inputs})")
        steps_str = '\n'.join(steps_desc)

        client = get_openai_client()
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": (
                    "You verify geographic computation results.\n"
                    "Given a query, the parsed steps, and the resulting coordinates,\n"
                    "determine if the result is geographically plausible.\n\n"
                    "Check:\n"
                    "- Is the result in the correct country/region?\n"
                    "- Is the distance roughly correct?\n"
                    "- Is the direction correct?\n\n"
                    "Reply ONLY: PLAUSIBLE or IMPLAUSIBLE followed by a one-line reason."
                )},
                {"role": "user", "content": (
                    f"Query: {text}\n\n"
                    f"Steps:\n{steps_str}\n\n"
                    f"Result coordinates: ({final_centroid[0]:.5f}, {final_centroid[1]:.5f})"
                )},
            ],
        )
        answer = resp.choices[0].message.content.strip()
        is_plausible = answer.upper().startswith("PLAUSIBLE")
        logger.info("Verification: %s — %s", "PASS" if is_plausible else "FAIL", answer[:80])
        return is_plausible
    except Exception as e:
        logger.error("Verification error: %s", e)
        return True  # assume OK on error


# ── Main entry point ─────────────────────────────────────

_SIMPLE_PROMPT = (
    _BASE_PROMPT +
    "Examples:\n"
    "<<<JSON>>>\n"
    '[{"id": 1, "function": "Relative", "inputs": ["Kazan", "north", "5 km"]}]\n'
    "<<<END>>>\n\n"
    "<<<JSON>>>\n"
    '[{"id": 1, "function": "Between", "inputs": ["Paris", "London"]}]\n'
    "<<<END>>>"
)


def parse(text, use_fewshot=True):
    """Parse text into positioning steps.

    Args:
        text: natural language query
        use_fewshot: if True, use type-specific few-shot examples (precise mode).
                     if False, use minimal prompt (fast mode).

    Returns list of step dicts.
    Raises ValueError if parsing fails.
    """
    original_text = text

    # Auto-translate Russian
    if _has_cyrillic(text):
        text = _translate_to_english(text)

    logger.info("Parsing (%s): '%s'", "precise" if use_fewshot else "fast", text[:80])

    # Attempt 1: parse
    if use_fewshot:
        steps = _call_llm(text)  # uses _build_prompt with targeted examples
    else:
        steps = _call_llm(text, system_prompt=_SIMPLE_PROMPT)  # minimal prompt
    if steps:
        return steps

    # Attempt 2: simplify and retry
    simplified = _simplify_text(text)
    if simplified != text:
        steps = _call_llm(simplified)
        if steps:
            return steps

    # Attempt 3: fallback to single Locate
    try:
        client = get_openai_client()
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "Extract the most specific place name. Output ONLY the name."},
                {"role": "user", "content": text},
            ],
        )
        place = resp.choices[0].message.content.strip()
        if place and place.upper() != "UNKNOWN":
            return [{"id": 1, "function": "Locate", "inputs": [place]}]
    except Exception:
        pass

    raise ValueError(f"Cannot parse: '{text}'")


def parse_and_verify(text, execute_fn):
    """Parse text, execute steps, verify result. Retry on implausible results.

    Args:
        text: user query
        execute_fn: function that takes steps and returns {id: (coords, centroid)}

    Returns:
        (steps, step_data) tuple
    """
    for attempt in range(2):
        steps = parse(text)
        step_data = execute_fn(steps)

        final_key = max(step_data.keys())
        _, final_centroid = step_data[final_key]

        if attempt == 0:
            # Verify first attempt
            if _verify_result(text, steps, final_centroid):
                return steps, step_data
            logger.warning("Verification failed, retrying with simplified text...")
        else:
            # Second attempt — accept regardless
            return steps, step_data

    return steps, step_data
