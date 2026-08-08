"""FastAPI application — SpatialParse REST API with WebSocket streaming."""

import json
import logging
import os
import re
from html import escape as escape_xml
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field

from backend.auth_store import (
    account_summary,
    authenticate_user,
    clear_history,
    create_session,
    create_user,
    delete_user_account,
    delete_history_item,
    delete_saved_place,
    delete_session,
    export_account_data,
    get_user_by_token,
    init_db,
    list_history,
    list_saved_places,
    record_user_consent,
    save_history,
    save_place,
    update_user_name,
)
from backend.llm_parser import parse, parse_and_verify, _has_cyrillic, _translate_to_english
from backend.geo_engine import execute_steps, make_geojson, get_coordinates, \
    relative, azimuth, between, fraction, toward, along, intersection, \
    near, inside, street_turn, make_circle, _to_centroid, _try_parse_step_ref, \
    resolve_pair_centroids
from backend.geo_math import parse_distance, parse_angle, direction_to_bearing

# Strings that should NOT be treated as place names for ref_points
_NOT_PLACES = {
    'north','south','east','west','northeast','northwest',
    'southeast','southwest','adjacent','close','vicinity','region',
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="SpatialParse", version="2.0")
init_db()

_DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:8001,"
    "http://localhost:8001,"
    "http://127.0.0.1:8000,"
    "http://localhost:8000"
)
_CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("SPATIALPARSE_CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=512)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://unpkg.com https://*.tile.openstreetmap.org; "
        "connect-src 'self' ws: wss: https://openrouter.ai https://nominatim.openstreetmap.org https://router.project-osrm.org https://overpass-api.de; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
SITE_DIR = Path(__file__).parent.parent / "spatialparse_site"
SITE_PAGES = [
    "index.html",
    "features.html",
    "demo.html",
    "docs.html",
    "pricing.html",
    "about.html",
    "privacy.html",
    "terms.html",
    "consent.html",
]


# ── Models ────────────────────────────────────────────────

class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    mode: str = "fast"
    uncertainty: bool = False
    draw_roads: bool = False


class StepResult(BaseModel):
    coordinates: list
    centroid: list[float]


class ParseResponse(BaseModel):
    text: str
    translated: str | None = None
    mode: str = "fast"
    steps: list[dict]
    results: dict[str, StepResult]
    final: StepResult
    geojson: dict
    road_geometries: dict[str, list] = Field(default_factory=dict)
    step_metadata: dict[str, dict] = Field(default_factory=dict)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=80)
    consent_accepted: bool = False
    consent_version: str = Field(default="2026-08-03", min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class ProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class HistoryCreateRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: str = "fast"
    steps: list[dict] = Field(default_factory=list)
    geojson: dict = Field(default_factory=dict)
    final: dict | None = None


class SavedPlaceCreateRequest(BaseModel):
    title: str = Field(default="", max_length=120)
    query: str = Field(default="", max_length=500)
    lon: float | None = None
    lat: float | None = None
    geojson: dict = Field(default_factory=dict)


# ── Helper: format step result for JSON ───────────────────

_ALLOWED_MODES = {"fast", "precise"}


def _normalize_mode(mode):
    mode = str(mode or "fast").strip().lower()
    if mode not in _ALLOWED_MODES:
        raise ValueError(f"Unsupported mode '{mode}'. Use 'fast' or 'precise'.")
    return mode


def _format_step_result(coords, centroid):
    coords_clean = []
    if isinstance(coords, list):
        for p in coords:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                coords_clean.append([float(p[0]), float(p[1])])
    return {
        "coordinates": coords_clean,
        "centroid": [float(centroid[0]), float(centroid[1])],
    }


def _polygon_ring(feature):
    geometry = feature.get("geometry", {}) or {}
    if geometry.get("type") != "Polygon":
        return []
    coords = geometry.get("coordinates") or []
    if not coords or not isinstance(coords[0], list):
        return []
    return coords[0]


def _reference_point(name, centroid):
    return {
        "name": str(name),
        "lon": round(float(centroid[0]), 6),
        "lat": round(float(centroid[1]), 6),
    }


def _is_step_reference(value):
    if isinstance(value, int):
        return True
    if not isinstance(value, str):
        return False
    return bool(re.search(r"(?i)(step|result|output)\s*#?\s*\d+|^#?\d+$", value.strip()))


def _pair_reference_data(inputs, c1, c2):
    ref_points = []
    for raw, centroid in zip(inputs[:2], (c1, c2)):
        if isinstance(raw, str) and not _is_step_reference(raw):
            ref_points.append(_reference_point(raw, centroid))

    return ref_points, [[float(c1[0]), float(c1[1])], [float(c2[0]), float(c2[1])]]


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or None
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else None


def _current_user(authorization: str | None = Header(default=None)):
    token = _bearer_token(authorization)
    user = get_user_by_token(token or "")
    if not user:
        raise HTTPException(status_code=401, detail="Требуется вход в аккаунт")
    return user


def _final_centroid(payload: dict | None) -> list[float] | None:
    if not payload:
        return None
    centroid = payload.get("centroid")
    if isinstance(centroid, list) and len(centroid) >= 2:
        return centroid
    result = payload.get("result")
    if isinstance(result, dict):
        centroid = result.get("centroid")
        if isinstance(centroid, list) and len(centroid) >= 2:
            return centroid
    return None


def _resolve_inputs_for_routes(inputs, data):
    resolved = []
    for inp in inputs:
        if isinstance(inp, int) and inp in data:
            resolved.append(data[inp])
        elif isinstance(inp, int):
            resolved.append(inp)
        else:
            ref = _try_parse_step_ref(inp, data)
            resolved.append(data[ref] if ref else inp)
    return resolved


def _rest_road_geometries(steps: list[dict], step_data: dict[int, tuple]) -> dict[str, list]:
    roads: dict[str, list] = {}
    if not steps or not step_data:
        return roads

    from backend.geo_engine import road_route

    for step in steps:
        sid = step.get("id")
        if sid not in step_data:
            continue

        func = step.get("function")
        inputs = step.get("inputs", [])
        resolved = _resolve_inputs_for_routes(inputs, step_data)
        route_start = None
        route_end = step_data[sid][1]

        try:
            if func in ("Relative", "Azimuth") and resolved:
                route_start = _to_centroid(resolved[0])
            elif func in ("Between", "Fraction", "Toward", "Along") and len(resolved) >= 2:
                c1, c2 = resolve_pair_centroids(resolved[0], resolved[1])
                route_start = c1
                route_end = c2
            elif isinstance(sid, int) and sid > 1 and (sid - 1) in step_data:
                route_start = step_data[sid - 1][1]

            if route_start is None or route_end is None:
                continue

            route_coords, _ = road_route(route_start[0], route_start[1], route_end[0], route_end[1])
            if route_coords:
                roads[str(sid)] = route_coords
        except Exception as exc:
            logger.warning("REST road geometry failed for step %s: %s", sid, exc)

    return roads


def _rest_step_metadata(steps: list[dict], step_data: dict[int, tuple]) -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    if not steps or not step_data:
        return metadata

    for step in steps:
        sid = step.get("id")
        if sid not in step_data:
            continue

        func = step.get("function")
        inputs = step.get("inputs", [])
        resolved = _resolve_inputs_for_routes(inputs, step_data)
        step_ref_points = []
        step_reference_geometry = None

        try:
            if func in ("Locate", "Location") and inputs:
                raw = inputs[0]
                if isinstance(raw, str):
                    _, centroid = step_data[sid]
                    step_ref_points.append(_reference_point(raw, centroid))
            elif func in ("Relative", "Azimuth") and resolved:
                origin = _to_centroid(resolved[0])
                _, centroid = step_data[sid]
                step_reference_geometry = [
                    [float(origin[0]), float(origin[1])],
                    [float(centroid[0]), float(centroid[1])],
                ]
                if isinstance(inputs[0], str) and not _is_step_reference(inputs[0]):
                    step_ref_points.append(_reference_point(inputs[0], origin))
            elif func in ("Between", "Fraction", "Toward", "Along") and len(resolved) >= 2:
                c1, c2 = resolve_pair_centroids(resolved[0], resolved[1])
                step_ref_points, step_reference_geometry = _pair_reference_data(inputs, c1, c2)
        except Exception as exc:
            logger.warning("REST metadata failed for step %s: %s", sid, exc)

        entry = {}
        if step_ref_points:
            entry["ref_points"] = step_ref_points
        if step_reference_geometry:
            entry["reference_geometry"] = step_reference_geometry
        if entry:
            metadata[str(sid)] = entry

    return metadata


# ── Auth and account endpoints ─────────────────────────────

@app.post("/api/auth/register")
def register(req: RegisterRequest, request: Request):
    if not req.consent_accepted:
        raise HTTPException(status_code=422, detail="Необходимо принять условия и согласие на обработку данных")
    consent_version = req.consent_version.strip()
    if not consent_version:
        raise HTTPException(status_code=422, detail="Версия документа не должна быть пустой")
    try:
        user = create_user(req.email, req.password, req.name)
        record_user_consent(
            user_id=user["id"],
            consent_type="registration_terms_privacy_personal_data",
            document_version=consent_version,
            accepted=True,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    token = create_session(user["id"])
    return {"token": token, "user": user, "summary": account_summary(user["id"])}


@app.post("/api/auth/login")
def login(req: LoginRequest):
    user = authenticate_user(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    token = create_session(user["id"])
    return {"token": token, "user": user, "summary": account_summary(user["id"])}


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    token = _bearer_token(authorization)
    if token:
        delete_session(token)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user=Depends(_current_user)):
    return {"user": user, "summary": account_summary(user["id"])}


@app.patch("/api/account/profile")
def update_profile(req: ProfileUpdateRequest, user=Depends(_current_user)):
    try:
        updated = update_user_name(user["id"], req.name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"user": updated, "summary": account_summary(user["id"])}


@app.get("/api/history")
def get_history(limit: int = 30, user=Depends(_current_user)):
    return {"items": list_history(user["id"], limit=limit)}


@app.post("/api/history")
def add_history(req: HistoryCreateRequest, user=Depends(_current_user)):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Запрос не должен быть пустым")
    item = save_history(
        user["id"],
        query=query,
        mode=_normalize_mode(req.mode),
        steps=req.steps,
        geojson=req.geojson,
        centroid=_final_centroid(req.final),
    )
    return {"item": item, "summary": account_summary(user["id"])}


@app.delete("/api/history/{item_id}")
def remove_history(item_id: int, user=Depends(_current_user)):
    if not delete_history_item(user["id"], item_id):
        raise HTTPException(status_code=404, detail="Запись истории не найдена")
    return {"ok": True, "summary": account_summary(user["id"])}


@app.delete("/api/history")
def remove_all_history(user=Depends(_current_user)):
    deleted = clear_history(user["id"])
    return {"ok": True, "deleted": deleted, "summary": account_summary(user["id"])}


@app.get("/api/saved-places")
def get_saved_places(user=Depends(_current_user)):
    return {"items": list_saved_places(user["id"])}


@app.post("/api/saved-places")
def add_saved_place(req: SavedPlaceCreateRequest, user=Depends(_current_user)):
    item = save_place(
        user["id"],
        title=req.title,
        query=req.query,
        lon=req.lon,
        lat=req.lat,
        geojson=req.geojson,
    )
    return {"item": item, "summary": account_summary(user["id"])}


@app.delete("/api/saved-places/{item_id}")
def remove_saved_place(item_id: int, user=Depends(_current_user)):
    if not delete_saved_place(user["id"], item_id):
        raise HTTPException(status_code=404, detail="Сохраненный результат не найден")
    return {"ok": True, "summary": account_summary(user["id"])}


@app.get("/api/account/export")
def export_account(user=Depends(_current_user)):
    payload = export_account_data(user["id"])
    content = json.dumps(payload, indent=2, ensure_ascii=False)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=spatialparse_account_export.json"},
    )


@app.delete("/api/account")
def delete_account(user=Depends(_current_user)):
    if not delete_user_account(user["id"]):
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    return {"ok": True}


# ── WebSocket streaming endpoint ─────────────────────────

@app.websocket("/ws/parse")
async def ws_parse(ws: WebSocket):
    await ws.accept()
    try:
        msg = await ws.receive_json()
        text = msg.get("text", "").strip()
        try:
            mode = _normalize_mode(msg.get("mode", "fast"))
        except ValueError as e:
            await ws.send_json({"type": "error", "message": str(e)})
            await ws.close()
            return
        unc = msg.get("uncertainty", False)
        snap = msg.get("snap_roads", False)
        draw_roads = msg.get("draw_roads", False)

        if not text:
            await ws.send_json({"type": "error", "message": "Text is empty"})
            await ws.close()
            return

        # Phase 1: Translation
        translated = None
        if _has_cyrillic(text):
            await ws.send_json({"type": "status", "message": "Перевод на английский..."})
            translated = _translate_to_english(text)
            await ws.send_json({"type": "translated", "translated": translated})

        # Phase 2: Parsing
        await ws.send_json({"type": "status", "message": "Анализ текста..."})
        steps = parse(text, use_fewshot=(mode == "precise"))
        await ws.send_json({"type": "steps", "steps": steps})

        # Phase 3: Execute step by step with streaming
        data = {}
        from shapely.geometry import Polygon

        for step in steps:
            sid = step["id"]
            func = step["function"]
            inputs = step.get("inputs", [])

            await ws.send_json({
                "type": "step_start",
                "step_id": sid,
                "function": func,
                "inputs": [str(i) if not isinstance(i, (int, float)) else i for i in inputs],
            })

            # Resolve references
            resolved = []
            for inp in inputs:
                if isinstance(inp, int) and inp in data:
                    resolved.append(data[inp])
                elif isinstance(inp, int):
                    resolved.append(inp)
                else:
                    ref = _try_parse_step_ref(inp, data)
                    resolved.append(data[ref] if ref else inp)

            # Execute
            try:
                step_route_start = None
                step_route_end = None
                step_ref_points = []
                step_reference_geometry = None

                if func == "Near":
                    place = resolved[0] if len(resolved) > 0 else ""
                    qualifier = resolved[1] if len(resolved) > 1 and isinstance(resolved[1], str) else "close"
                    data[sid] = near(place, qualifier)

                elif func == "Inside":
                    place = resolved[0] if len(resolved) > 0 else ""
                    data[sid] = inside(place)

                elif func in ("Locate", "Location"):
                    place = resolved[0]
                    if isinstance(place, str):
                        coords, centroid, radius = get_coordinates(place)
                        too_small = not isinstance(coords, list) or len(coords) < 3
                        if not too_small:
                            try:
                                too_small = Polygon(coords).area < 0.00001
                            except Exception:
                                too_small = True
                        if too_small:
                            coords, centroid = make_circle(centroid, radius_km=radius)
                        data[sid] = (coords, centroid)
                    else:
                        data[sid] = place

                elif func == "Relative":
                    loc, direction, distance = resolved
                    centroid = _to_centroid(loc)
                    step_route_start = centroid
                    data[sid] = relative(centroid, direction, str(distance), uncertainty=unc)
                    result_centroid = data[sid][1]
                    step_reference_geometry = [
                        [float(centroid[0]), float(centroid[1])],
                        [float(result_centroid[0]), float(result_centroid[1])],
                    ]

                elif func == "Between":
                    c1, c2 = resolve_pair_centroids(resolved[0], resolved[1])
                    step_ref_points, step_reference_geometry = _pair_reference_data(inputs, c1, c2)
                    step_route_start = c1
                    step_route_end = c2
                    data[sid] = between(c1, c2, uncertainty=unc)

                elif func == "Fraction":
                    c1, c2 = resolve_pair_centroids(resolved[0], resolved[1])
                    step_ref_points, step_reference_geometry = _pair_reference_data(inputs, c1, c2)
                    step_route_start = c1
                    step_route_end = c2
                    data[sid] = fraction(c1, c2, resolved[2], uncertainty=unc)

                elif func == "Azimuth":
                    loc, angle, distance = resolved
                    centroid = _to_centroid(loc)
                    step_route_start = centroid
                    data[sid] = azimuth(centroid, angle, str(distance), uncertainty=unc)
                    result_centroid = data[sid][1]
                    step_reference_geometry = [
                        [float(centroid[0]), float(centroid[1])],
                        [float(result_centroid[0]), float(result_centroid[1])],
                    ]

                elif func == "Toward":
                    c_from, c_toward = resolve_pair_centroids(resolved[0], resolved[1])
                    step_ref_points, step_reference_geometry = _pair_reference_data(inputs, c_from, c_toward)
                    step_route_start = c_from
                    data[sid] = toward(c_from, c_toward, str(resolved[2]), uncertainty=unc)

                elif func == "Along":
                    c_from, c_toward = resolve_pair_centroids(resolved[0], resolved[1])
                    step_ref_points, step_reference_geometry = _pair_reference_data(inputs, c_from, c_toward)
                    step_route_start = c_from
                    data[sid] = along(c_from, c_toward, str(resolved[2]), uncertainty=unc)

                elif func == "Intersection":
                    street1 = resolved[0] if len(resolved) > 0 else ""
                    street2 = resolved[1] if len(resolved) > 1 else ""
                    city_ctx = resolved[2] if len(resolved) > 2 and isinstance(resolved[2], str) else None
                    data[sid] = intersection(street1, street2, city_ctx)

                elif func == "StreetTurn":
                    street = resolved[0] if len(resolved) > 0 else ""
                    toward_place = resolved[1] if len(resolved) > 1 else ""
                    from_p = resolved[2] if len(resolved) > 2 and isinstance(resolved[2], str) else None
                    city_ctx = resolved[3] if len(resolved) > 3 and isinstance(resolved[3], str) else None
                    data[sid] = street_turn(street, toward_place, from_p, city_ctx)

                else:
                    raise ValueError(f"Unknown function: {func}")

                # Collect reference points (geocoded input places)
                ref_points = list(step_ref_points)
                ref_names = {rp["name"] for rp in ref_points}
                for inp in inputs:
                    if not isinstance(inp, str):
                        continue
                    if inp in ref_names:
                        continue
                    inp_lower = inp.lower().strip()
                    # Skip directions, qualifiers, distances, numbers
                    if inp_lower in _NOT_PLACES:
                        continue
                    if re.search(r'^\d+\.?\d*\s*(km|mi|miles|m|ft|°|degree)', inp_lower):
                        continue
                    if inp.replace('.','',1).lstrip('-').isdigit():
                        continue
                    try:
                        _, rp_centroid, _ = get_coordinates(inp)
                        ref_points.append({
                            "name": inp,
                            "lon": round(rp_centroid[0], 6),
                            "lat": round(rp_centroid[1], 6),
                        })
                    except Exception:
                        pass

                # Send step result immediately
                coords, centroid = data[sid]

                # Road snapping
                snapped = None
                if snap:
                    from backend.geo_engine import snap_to_road
                    snapped = snap_to_road(centroid[0], centroid[1])

                # Road distance/geometry between consecutive steps, or along a single Along() operation.
                road_info = None
                road_geometry = None
                route_start = step_route_start
                route_end = step_route_end
                if route_start is None and sid > 1 and (sid - 1) in data:
                    route_start = data[sid - 1][1]
                if route_end is None:
                    route_end = centroid

                if route_start is not None and route_end is not None:
                    from backend.geo_engine import road_distance, road_route
                    road_km, straight_km = road_distance(
                        route_start[0], route_start[1], route_end[0], route_end[1])
                    road_info = {
                        "road_km": round(road_km, 2),
                        "straight_km": round(straight_km, 2),
                        "ratio": round(road_km / straight_km, 2) if straight_km > 0 else 1,
                    }
                    # Road route geometry (only if toggle is on)
                    if draw_roads:
                        route_coords, _ = road_route(
                            route_start[0], route_start[1], route_end[0], route_end[1])
                        if route_coords:
                            road_geometry = route_coords  # [[lon,lat], ...]

                result = _format_step_result(coords, centroid)
                is_final = sid == steps[-1]["id"]

                step_msg = {
                    "type": "step_result",
                    "step_id": sid,
                    "function": func,
                    "inputs": [str(i) if not isinstance(i, (int, float)) else i for i in inputs],
                    "result": result,
                    "is_final": is_final,
                }
                if snapped:
                    step_msg["snapped"] = [round(snapped[0], 6), round(snapped[1], 6)]
                if road_info:
                    step_msg["road_info"] = road_info
                if road_geometry:
                    step_msg["road_geometry"] = road_geometry
                if ref_points:
                    step_msg["ref_points"] = ref_points
                if step_reference_geometry:
                    step_msg["reference_geometry"] = step_reference_geometry

                await ws.send_json(step_msg)

            except Exception as e:
                await ws.send_json({
                    "type": "step_error",
                    "step_id": sid,
                    "error": str(e),
                })

        # Phase 4: Verification (precise mode only)
        if mode == "precise" and data:
            await ws.send_json({"type": "status", "message": "Верификация результата..."})
            from backend.llm_parser import _verify_result
            final_key = max(data.keys())
            _, final_centroid = data[final_key]
            plausible = _verify_result(text, steps, final_centroid)
            await ws.send_json({
                "type": "verification",
                "plausible": plausible,
            })

        # Phase 5: Final GeoJSON
        geojson = make_geojson(data, steps)
        await ws.send_json({"type": "complete", "geojson": geojson})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e, exc_info=True)
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


# ── REST endpoint (kept for tests/compatibility) ─────────

@app.post("/api/parse", response_model=ParseResponse)
def parse_text(req: ParseRequest):
    original_text = req.text.strip()
    if not original_text:
        raise HTTPException(400, "Text is empty")

    try:
        mode = _normalize_mode(req.mode)
        translated = None
        if _has_cyrillic(original_text):
            translated = _translate_to_english(original_text)

        if mode == "precise":
            steps, step_data = parse_and_verify(
                original_text,
                lambda parsed_steps: execute_steps(parsed_steps, uncertainty=req.uncertainty),
            )
        else:
            steps = parse(original_text, use_fewshot=False)
            step_data = execute_steps(steps, uncertainty=req.uncertainty)

        if not step_data:
            raise ValueError("No executable steps were produced")

        results = {}
        for sid, (coords, centroid) in step_data.items():
            results[str(sid)] = StepResult(**_format_step_result(coords, centroid))

        final_key = str(max(step_data.keys()))
        geojson = make_geojson(step_data, steps)
        road_geometries = _rest_road_geometries(steps, step_data) if req.draw_roads else {}
        step_metadata = _rest_step_metadata(steps, step_data)

        return ParseResponse(
            text=original_text, translated=translated, mode=mode,
            steps=steps, results=results, final=results[final_key], geojson=geojson,
            road_geometries=road_geometries, step_metadata=step_metadata,
        )

    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        logger.error("Parse error: %s", e, exc_info=True)
        raise HTTPException(500, f"Internal error: {e}")


# ── Export endpoints ──────────────────────────────────────


@app.post("/api/export/geojson")
def export_geojson(req: dict):
    """Return GeoJSON as downloadable file."""
    geojson = req.get("geojson", {})
    content = json.dumps(geojson, indent=2, ensure_ascii=False)
    return Response(
        content=content,
        media_type="application/geo+json",
        headers={"Content-Disposition": "attachment; filename=spatialparse_result.geojson"},
    )


@app.post("/api/export/kml")
def export_kml(req: dict):
    """Convert GeoJSON to KML and return as downloadable file."""
    geojson = req.get("geojson", {})
    kml = _geojson_to_kml(geojson)
    return Response(
        content=kml,
        media_type="application/vnd.google-earth.kml+xml",
        headers={"Content-Disposition": "attachment; filename=spatialparse_result.kml"},
    )


@app.post("/api/export/gpx")
def export_gpx(req: dict):
    """Convert GeoJSON to GPX and return as downloadable file."""
    geojson = req.get("geojson", {})
    gpx = _geojson_to_gpx(geojson)
    return Response(
        content=gpx,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": "attachment; filename=spatialparse_result.gpx"},
    )


def _geojson_to_kml(geojson):
    """Convert GeoJSON FeatureCollection to KML."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Document>',
        '<name>SpatialParse Result</name>',
    ]
    colors_kml = ['ff0000ff', 'ff00ff00', 'ff00a5ff', 'ffff00ff', 'ffffff00', 'ff0000ff']

    for i, feature in enumerate(geojson.get("features", [])):
        props = feature.get("properties", {})
        sid = props.get("step_id", i + 1)
        func = props.get("function", "?")
        inputs = props.get("inputs", [])
        centroid = props.get("centroid", [0, 0])
        is_final = props.get("is_final", False)
        color = 'ff0000ff' if is_final else colors_kml[i % len(colors_kml)]
        func_xml = escape_xml(str(func))
        desc_xml = escape_xml(f'{func}({", ".join(str(x) for x in inputs)})')

        # Placemark for centroid
        lines.append(f'  <Placemark>')
        lines.append(f'    <name>Step {sid}: {func_xml}</name>')
        lines.append(f'    <description>{desc_xml}</description>')
        lines.append(f'    <Point><coordinates>{centroid[0]},{centroid[1]},0</coordinates></Point>')
        lines.append(f'  </Placemark>')

        # Polygon
        ring = _polygon_ring(feature)
        if len(ring) > 1:
            lines.append(f'  <Placemark>')
            lines.append(f'    <name>Step {sid} area</name>')
            lines.append(f'    <Style><PolyStyle><color>80{color[2:]}</color></PolyStyle>'
                         f'<LineStyle><color>{color}</color><width>2</width></LineStyle></Style>')
            lines.append(f'    <Polygon><outerBoundaryIs><LinearRing><coordinates>')
            coord_str = ' '.join(f'{p[0]},{p[1]},0' for p in ring)
            lines.append(f'      {coord_str}')
            lines.append(f'    </coordinates></LinearRing></outerBoundaryIs></Polygon>')
            lines.append(f'  </Placemark>')

    lines.append('</Document>')
    lines.append('</kml>')
    return '\n'.join(lines)


def _geojson_to_gpx(geojson):
    """Convert GeoJSON FeatureCollection to GPX."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="SpatialParse"'
        ' xmlns="http://www.topografix.com/GPX/1/1">',
    ]

    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        sid = props.get("step_id", 0)
        func = props.get("function", "?")
        inputs = props.get("inputs", [])
        centroid = props.get("centroid", [0, 0])
        func_xml = escape_xml(str(func))
        desc_xml = escape_xml(f'{func}({", ".join(str(x) for x in inputs)})')

        # Waypoint for centroid
        lines.append(f'  <wpt lat="{centroid[1]}" lon="{centroid[0]}">')
        lines.append(f'    <name>Step {sid}: {func_xml}</name>')
        lines.append(f'    <desc>{desc_xml}</desc>')
        lines.append(f'  </wpt>')

        # Track from polygon
        ring = _polygon_ring(feature)
        if len(ring) > 1:
            lines.append(f'  <trk><name>Step {sid} area</name><trkseg>')
            for p in ring:
                lines.append(f'    <trkpt lat="{p[1]}" lon="{p[0]}"></trkpt>')
            lines.append(f'  </trkseg></trk>')

    lines.append('</gpx>')
    return '\n'.join(lines)


# ── Static frontend ──────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


def _public_base_url(request: Request) -> str:
    configured = os.getenv("SPATIALPARSE_PUBLIC_URL", "").strip().rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


@app.get("/favicon.ico")
def favicon():
    return FileResponse(str(SITE_DIR / "favicon.svg"), media_type="image/svg+xml")


@app.get("/site.webmanifest")
def webmanifest():
    return FileResponse(str(SITE_DIR / "site.webmanifest"), media_type="application/manifest+json")


@app.get("/robots.txt")
def robots(request: Request):
    base = _public_base_url(request)
    return Response(
        f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n",
        media_type="text/plain",
    )


@app.get("/sitemap.xml")
def sitemap(request: Request):
    base = _public_base_url(request)
    urls = "\n".join(f"  <url><loc>{base}/site/{page}</loc></url>" for page in SITE_PAGES)
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n",
        media_type="application/xml",
    )

if SITE_DIR.exists():
    @app.get("/site")
    def site_redirect():
        return RedirectResponse(url="/site/")

    app.mount("/site", StaticFiles(directory=str(SITE_DIR), html=True), name="spatialparse_site")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
