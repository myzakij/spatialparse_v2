# SpatialParse v2 - описание проекта для языковой модели

Дата актуализации: 2026-08-03.

Этот документ предназначен для языковой модели или кодового ассистента, которому нужно быстро понять проект SpatialParse v2, не перечитывая весь репозиторий с нуля. Документ не содержит секретов из `.env`.

## 1. Краткое назначение

SpatialParse v2 - это геопространственная NLP-система. Пользователь пишет естественный текст, например:

```text
Середина между Осиново и Юдино
5 км к северо-востоку от Казанского Кремля
15 км по направлению к Иннополису от центра Казани
```

Система преобразует текст в цепочку формальных пространственных функций, выполняет геокодинг и геометрические расчеты, после чего показывает результат на карте.

Основной сценарий:

1. Пользователь вводит географическое описание на сайте.
2. Frontend отправляет запрос в FastAPI backend через WebSocket `/ws/parse`.
3. Backend при необходимости переводит русский текст, вызывает LLM через OpenRouter и получает JSON шагов.
4. Геодвижок исполняет шаги: геокодинг, смещения, середины, доли пути, направления, дороги, пересечения улиц.
5. Backend стримит промежуточные события на frontend.
6. Leaflet-карта рисует опорные точки, пунктирные линии, итоговые области, маркеры и дорожные маршруты.
7. Авторизованный пользователь может сохранять историю и результаты в локальную SQLite-базу.

## 2. Текущая модель и внешние сервисы

LLM работает через OpenRouter.

Файл: `backend/config.py`

```python
DEFAULT_MODEL = "deepseek/deepseek-v4-pro"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
```

Переменные окружения:

```text
OPENROUTER_API_KEY=...
SPATIALPARSE_TLS_VERIFY=true|false
```

Не выводить и не коммитить реальные значения `.env`.

Внешние сервисы:

| Сервис | Где используется | Назначение |
|---|---|---|
| OpenRouter | `backend/llm_parser.py`, `backend/geo_engine.py` | Парсинг текста, перевод, подсказки для геокодинга |
| Nominatim / OpenStreetMap | `backend/geo_engine.py` | Геокодинг топонимов |
| OSRM public router | `backend/geo_engine.py` | Маршруты и расстояния по дорогам |
| Overpass API | `backend/geo_engine.py` | Геометрия улиц для `Intersection` и `StreetTurn` |

## 3. Главная структура репозитория

```text
SpatialParse_v2/
  backend/
    main.py          FastAPI API, WebSocket, export, static site mount
    llm_parser.py    LLM prompt, перевод, парсинг текста в spatial steps
    geo_engine.py    Геокодинг, spatial-функции, дороги, улицы, GeoJSON
    geo_math.py      Математика: расстояния, bearing, круги, эллипсы
    config.py        Конфиг OpenRouter, Nominatim, cache, направления
    auth_store.py    SQLite auth, sessions, history, saved places

  spatialparse_site/
    index.html       Главная страница сайта
    demo.html        Рабочая карта и запуск запросов
    account.html     Кабинет пользователя
    docs.html        Документация на сайте
    app.js           Общая логика UI, WebSocket, Leaflet, auth
    style.css        Визуальный стиль сайта

  frontend/
    index.html       Старый/legacy frontend. Сейчас основная версия сайта в spatialparse_site/

  tests/
    test_spatial_core.py      Основные регрессионные тесты ядра
    test_accuracy.py          Accuracy/evaluation отчеты
    test_gbif.py              GBIF locality tests
    compare_models.py         Сравнение моделей через OpenRouter
    ...                       HTML/JSON отчеты и вспомогательные тесты

  dataset/
    dataset_*.json            Тестовые наборы запросов
    gold_standard.json        Gold-разметка

  datasets_extended/
    *.json                    Расширенные датасеты
    gbif/*.csv                GBIF locality datasets

  thesis/
    *.md                      Материалы диссертации/описания

  SYSTEM_PROMPTS.md           Сводка системных промптов приложения
  requirements.txt            Python зависимости
  Dockerfile                  Docker запуск backend
  geocache.db                 SQLite cache геокодинга и LLM-помощников
  spatialparse.db             SQLite auth/history/saved places
```

## 4. Backend: FastAPI

Главный файл: `backend/main.py`.

Приложение:

```python
app = FastAPI(title="SpatialParse", version="2.0")
```

### 4.1 Основные endpoints

| Endpoint | Назначение |
|---|---|
| `GET /api/health` | Проверка, что backend жив |
| `POST /api/parse` | REST fallback для парсинга и вычисления |
| `WS /ws/parse` | Основной live-поток шагов для сайта |
| `POST /api/export/geojson` | Экспорт GeoJSON |
| `POST /api/export/kml` | Экспорт KML |
| `POST /api/export/gpx` | Экспорт GPX |
| `POST /api/auth/register` | Регистрация |
| `POST /api/auth/login` | Вход |
| `POST /api/auth/logout` | Выход |
| `GET /api/auth/me` | Текущий пользователь и summary |
| `GET /api/history` | История запросов |
| `POST /api/history` | Сохранить запуск в историю |
| `DELETE /api/history/{item_id}` | Удалить запись истории |
| `GET /api/saved-places` | Сохраненные результаты |
| `POST /api/saved-places` | Сохранить результат |
| `DELETE /api/saved-places/{item_id}` | Удалить сохраненный результат |

Static mount:

```text
/site/    -> spatialparse_site/
/static/  -> frontend/
```

Текущий удобный URL для сайта:

```text
http://127.0.0.1:8001/site/demo.html
```

Обычный backend port из Dockerfile:

```text
8000
```

В локальной разработке часто используется:

```text
8001
```

## 5. WebSocket protocol

Frontend отправляет на `WS /ws/parse` JSON:

```json
{
  "text": "Середина между Осиново и Юдино",
  "mode": "fast",
  "uncertainty": false,
  "draw_roads": true
}
```

Поддерживаемые `mode`:

```text
fast
precise
```

Backend отправляет события:

| type | Когда отправляется | Важные поля |
|---|---|---|
| `status` | Смена стадии | `message` |
| `translated` | Если исходный текст кириллический | `translated` |
| `steps` | После LLM-парсинга | `steps` |
| `step_start` | Перед выполнением шага | `step_id`, `function`, `inputs` |
| `step_result` | После успешного шага | `result`, `road_geometry`, `reference_geometry`, `ref_points`, `road_info` |
| `step_error` | Ошибка отдельного шага | `step_id`, `error` |
| `verification` | Только в `precise` | `plausible` |
| `complete` | Финал | `geojson` |
| `error` | Общая ошибка | `message` |

`step_result.result` имеет вид:

```json
{
  "coordinates": [[49.1, 55.8], [49.2, 55.9]],
  "centroid": [49.15, 55.85]
}
```

Координаты в backend и JSON обычно хранятся как `[lon, lat]`. Leaflet на frontend получает их как `[lat, lon]` через `toLatLngs()`.

## 6. LLM parser

Главный файл: `backend/llm_parser.py`.

Задача parser: превратить текст пользователя в минимальную цепочку spatial steps.

Формат шага:

```json
{
  "id": 1,
  "function": "Between",
  "inputs": ["Osinovo, Tatarstan", "Yudino, Kazan"]
}
```

LLM должна вернуть JSON между маркерами:

```text
<<<JSON>>>
[{"id": 1, "function": "Relative", "inputs": ["Kazan Kremlin", "northeast", "5 km"]}]
<<<END>>>
```

### 6.1 Доступные spatial functions

| Function | Inputs | Смысл |
|---|---|---|
| `Locate(place)` | `place` | Найти место |
| `Relative(location, direction, distance)` | location, direction, distance | Смещение по сторонам света |
| `Between(location1, location2)` | loc1, loc2 | Геометрическая середина |
| `Fraction(location1, location2, ratio)` | loc1, loc2, ratio | Доля отрезка между точками |
| `Azimuth(location, angle, distance)` | loc, degrees, distance | Смещение по азимуту |
| `Toward(from_place, toward_place, distance)` | from, toward, distance | Смещение от A в направлении B по прямой |
| `Along(from_place, toward_place, distance)` | from, toward, distance | Движение по дорожной сети |
| `Intersection(street1, street2, city)` | street1, street2, city | Пересечение улиц |
| `Near(place, qualifier)` | place, qualifier | Нечеткая близость |
| `Inside(place)` | place | Граница или область объекта |
| `StreetTurn(street, toward_place, from_place, city)` | street, toward, from, city | Точка поворота с улицы к ориентиру |

### 6.2 Важные правила parser

1. Использовать минимальное число шагов.
2. Направления должны быть на английском: `north`, `south`, `east`, `west`, `northeast`, `northwest`, `southeast`, `southwest`.
3. Если направление выражено местом, использовать `Toward` или `Along`, а не `Relative`.
4. Если явно сказано "по дороге", "по трассе", "along road/highway", использовать `Along`.
5. Для русских или неоднозначных топонимов желательно добавлять контекст: `Kazan`, `Tatarstan`, `Russia`.
6. Ссылки на предыдущие шаги должны быть integer id, например `1`, а не строка `"step1"`.
7. Backend дополнительно умеет распознавать строки вида `"Step 1"`, `"Result1"`, `"RelativeResult2"`, но LLM лучше выдавать integer.

## 7. Geo engine

Главный файл: `backend/geo_engine.py`.

### 7.1 Геокодинг

Основной публичный метод:

```python
get_coordinates(location)
```

Он:

1. Строит варианты запроса через `_build_query_variants()`.
2. Учитывает страну/контекст через `_resolve_location_context()`.
3. Идет в Nominatim через `_nominatim_search()`.
4. Кеширует результаты в `geocache.db`.
5. Возвращает:

```python
(coords, centroid, radius)
```

Где:

```text
coords   - geojson-подобная геометрия или точка
centroid - tuple(lon, lat)
radius   - радиус неопределенности в километрах
```

### 7.2 Контекст для неоднозначных мест

Для парных операций есть важная функция:

```python
resolve_pair_centroids(loc1, loc2, max_pair_distance_km=250, context_radius_km=120)
```

Она нужна, чтобы запросы вроде:

```text
Середина между Высокой Горой и Дербышками
```

не выбирали "Высокую Гору" за 1000+ км. Логика:

1. Сначала геокодятся обе точки.
2. Если расстояние слишком большое, одна точка используется как контекст для другой.
3. `get_coordinates_near()` ограничивает поиск viewbox-областью вокруг уже найденного маркера.
4. Если новая пара стала ближе, она используется вместо исходной.

Это критичная логика для Казани, Татарстана и соседних поселений.

### 7.3 Дорожные маршруты

OSRM функции:

```python
snap_to_road(lon, lat)
road_distance(lon1, lat1, lon2, lat2)
road_route(lon1, lat1, lon2, lat2)
```

Текущая логика WebSocket-отрисовки дорог в `backend/main.py`:

| Function | Откуда строится дорога | Куда строится дорога |
|---|---|---|
| `Relative` | исходная точка | вычисленная точка |
| `Azimuth` | исходная точка | вычисленная точка |
| `Between` | первая опорная точка | вторая опорная точка |
| `Fraction` | первая опорная точка | вторая опорная точка |
| `Toward` | стартовая точка | вычисленная точка |
| `Along` | стартовая точка | вычисленная точка по дороге |
| цепочки из нескольких шагов | предыдущий centroid | текущий centroid |

Важное проектное решение:

```text
Relative/Azimuth считают результат геометрически.
Если включен draw_roads, дорога рисуется как визуальный слой от базы до результата.
```

Пример:

```text
5 км к северо-востоку от Казанского Кремля
```

Результат:

1. Точка считается строго 5 км по прямому азимуту.
2. Серая пунктирная линия показывает геометрическое направление.
3. Синяя линия показывает дорожный маршрут от Кремля до района вычисленной точки.

Для будущего улучшения:

```text
5 км по дороге от Кремля на северо-восток
```

Это другой смысл. Нужно не просто строить дорогу до геометрической точки, а пройти 5 км по дорожной сети в выбранном направлении. Сейчас такая логика полностью не реализована для cardinal direction без второй целевой точки.

## 8. Math layer

Файл: `backend/geo_math.py`.

Ключевые функции:

| Function | Назначение |
|---|---|
| `parse_distance()` | Парсинг расстояний в километры |
| `parse_angle()` | Парсинг азимута |
| `haversine()` | Дистанция между координатами |
| `calculate_bearing()` | Bearing от точки A к точке B |
| `haversine_project()` | Проекция точки по bearing и distance |
| `make_circle()` | Полигон круга вокруг центра |
| `make_ellipse()` | Эллипс неопределенности |
| `uncertainty_for_function()` | Эвристика неопределенности для функций |

## 9. Auth и личный кабинет

Файл: `backend/auth_store.py`.

База:

```text
spatialparse.db
```

Таблицы:

| Таблица | Назначение |
|---|---|
| `users` | Пользователи |
| `sessions` | Bearer tokens |
| `parse_history` | История запусков |
| `saved_places` | Сохраненные результаты |

Пароли:

```text
PBKDF2-HMAC-SHA256, 260000 iterations
```

Сессии:

```text
token_urlsafe(32), срок по умолчанию 30 дней
```

Frontend хранит token в:

```text
localStorage["spatialparse_token"]
```

Шапка сайта показывает имя пользователя. По клику открывается dropdown-меню аккаунта:

1. Профиль и email.
2. Количество запросов.
3. Количество сохраненных результатов.
4. Последняя активность.
5. Переходы в кабинет, демо, историю, сохраненные результаты, рабочий контекст, документацию.
6. Обновление данных.
7. Выход.

## 10. Frontend

Основной frontend:

```text
spatialparse_site/
```

Legacy frontend:

```text
frontend/index.html
```

### 10.1 Страницы

| Страница | Назначение |
|---|---|
| `index.html` | Главная презентационная страница |
| `demo.html` | Рабочая карта, запросы, экспорт, сохранение |
| `account.html` | История, сохраненные результаты, рабочие настройки |
| `docs.html` | Пользовательская документация |

### 10.2 app.js

Файл: `spatialparse_site/app.js`.

Основные зоны ответственности:

| Функция | Назначение |
|---|---|
| `init()` | Инициализация всего сайта |
| `initWorkbench()` | Логика demo-страницы |
| `initWorkbenchMap()` | Leaflet карта demo |
| `initAccountMap()` | Leaflet карта кабинета |
| `runQuery()` | Запуск пользовательского запроса |
| `runWebSocket()` | Подключение к `/ws/parse` |
| `handleStreamMessage()` | Обработка событий backend |
| `handleStepResult()` | Обработка результата шага |
| `addStepToMap()` | Рисование итоговых областей и маркеров |
| `drawReferenceGeometry()` | Пунктирная опорная линия |
| `drawRoadGeometry()` | Красивая дорожная линия |
| `saveCurrentResult()` | Сохранение результата в кабинет |
| `exportCurrentResult()` | GeoJSON/KML/GPX export |
| `renderAccountMenu()` | Dropdown меню пользователя |

### 10.3 Карта и визуальные слои

Leaflet используется на demo, account и hero-картах.

Attribution Leaflet/OpenStreetMap скрыт:

```css
.leaflet-control-attribution {
  display: none !important;
}
```

Порядок кастомных panes:

```text
spZoneHaloPane   390
spZonePane       430
spReferencePane  570
spRoutePane      650
spMarkerPane     760
```

Визуальные классы:

| CSS class | Что рисует |
|---|---|
| `premium-zone-halo` | Мягкое свечение области |
| `premium-zone-fill` | Заливка области |
| `premium-zone-outline` | Граница области |
| `reference-line` | Пунктирная геометрическая линия |
| `premium-road-main` | Основная синяя дорожная линия |
| `premium-road-flow` | Анимированный поток по маршруту |
| `road-terminal` | Старт/финиш дорожного маршрута |
| `result-marker` | Маркер результата |

## 11. REST parse response

`POST /api/parse` принимает:

```json
{
  "text": "5 км к северо-востоку от Казанского Кремля",
  "mode": "fast",
  "uncertainty": false
}
```

Возвращает:

```json
{
  "text": "...",
  "translated": "...",
  "mode": "fast",
  "steps": [
    {"id": 1, "function": "Relative", "inputs": ["Kazan Kremlin", "northeast", "5 km"]}
  ],
  "results": {
    "1": {
      "coordinates": [],
      "centroid": [49.162719, 55.830769]
    }
  },
  "geojson": {}
}
```

REST не дает live-события. Основной UX использует WebSocket.

## 12. Export

Backend умеет экспортировать:

```text
GeoJSON
KML
GPX
```

Frontend вызывает:

```text
POST /api/export/geojson
POST /api/export/kml
POST /api/export/gpx
```

KML/GPX генераторы в `backend/main.py` экранируют XML-строки через `escape_xml`.

## 13. Кеши и базы данных

```text
geocache.db      - кеш Nominatim и LLM-помощников геокодинга
spatialparse.db  - пользователи, сессии, история, сохраненные результаты
```

Обе базы локальные SQLite. Во время реальных тестов геокодинга они могут изменяться.

Не удалять эти базы без явной команды пользователя.

## 14. Запуск

### 14.1 Локальный запуск

Из корня проекта:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

Открыть:

```text
http://127.0.0.1:8001/site/demo.html
```

Проверить backend:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8001/api/health
```

### 14.2 Docker

```powershell
docker build -t spatialparse-v2 .
docker run --env-file .env -p 8000:8000 spatialparse-v2
```

Открыть:

```text
http://127.0.0.1:8000/site/demo.html
```

## 15. Тесты и проверки

Быстрые проверки после правок backend/frontend:

```powershell
node --check spatialparse_site\app.js
python -m compileall backend tests
python -m unittest tests.test_spatial_core
```

`tests/test_spatial_core.py` покрывает:

1. Основные spatial-функции без сети.
2. `Along` с road geometry.
3. `Intersection` и `StreetTurn` без Overpass.
4. `Inside` с polygon boundary.
5. Ссылки на шаги строками.
6. Контекстную переякорку неоднозначного поселения.
7. WebSocket road geometry для `Along`.
8. WebSocket road geometry для `Relative`.
9. WebSocket road geometry для `Between`.
10. Reference geometry для парных операций.

Для accuracy/evaluation есть отдельные скрипты:

```text
tests/test_accuracy.py
tests/test_gbif.py
tests/compare_models.py
tests/dissertation_metrics.py
```

Они могут обращаться в сеть и быть медленными.

## 16. Важные недавние решения и исправления

### 16.1 Контекст для "Высокая Гора" и похожих топонимов

Проблема: Nominatim мог выбрать одноименное место за 1000+ км.

Решение:

```python
resolve_pair_centroids()
get_coordinates_near()
```

Если один маркер выглядит надежным, второй уточняется рядом с ним.

### 16.2 Дорожные линии для `Between`

Проблема: для `Between` точка результата была правильной, но дорожная линия не строилась, потому что backend не задавал route start/end.

Решение:

```text
Between/Fraction: road route from point A to point B
```

### 16.3 Дорожные линии для `Relative` и `Azimuth`

Проблема: запрос `5 км к северо-востоку от Казанского Кремля` давал точку, но не давал дорогу.

Решение:

```text
Relative/Azimuth: road route from base point to computed result
```

### 16.4 Улучшенная отрисовка карты

Добавлены:

1. Кастомные Leaflet panes.
2. Мягкие зоны с halo/fill/outline.
3. Синяя дорожная линия с белой обводкой и анимированным потоком.
4. Стартовые и конечные точки маршрута.
5. Пунктирные reference lines.
6. Улучшенные result markers.

### 16.5 Account dropdown

По клику на имя пользователя открывается меню аккаунта. Меню закрывается по Escape и клику вне блока. Проверено на desktop и mobile viewport 390px.

### 16.6 Убрана подпись Leaflet/OpenStreetMap

Attribution control отключен в `L.map(..., { attributionControl: false })` и дополнительно скрыт CSS.

## 17. UX текущего сайта

Текущий сайт стремится выглядеть как полноценный коммерческий продукт:

1. Плотная, аккуратная рабочая карта.
2. Минимум лишнего текста внутри рабочих поверхностей.
3. Демо как основной экран, а не маркетинговая заглушка.
4. Анимации раскрытия, hover-состояния, premium route rendering.
5. Личный кабинет с историей, сохраненными результатами и картой предпросмотра.

При будущих frontend-правках важно:

1. Не делать гигантские hero-блоки вместо рабочего интерфейса.
2. Не помещать карточки внутрь карточек.
3. Следить, чтобы текст не вылезал из кнопок/панелей.
4. Проверять mobile.
5. Для карт и 3D/Canvas всегда проверять визуально в браузере.

## 18. Known limitations

1. Public OSRM может быть недоступен или медленным. При отказе route geometry может отсутствовать, но система не должна падать.
2. Public Nominatim имеет rate limit. В коде есть rate limiting и cache.
3. `Along` требует начальную и целевую точку. Запросы вида "5 км по дороге на северо-восток от Кремля" требуют дальнейшей логики выбора дорожного направления без конечного места.
4. `frontend/index.html` является legacy и не отражает весь текущий сайт.
5. `geocache.db` и `spatialparse.db` могут изменяться при реальных прогонах.
6. Некоторые старые HTML/JSON отчеты в `tests/` являются артефактами оценки, а не runtime-кодом.
7. Терминал PowerShell может показывать русские строки как mojibake, но сайт в браузере отображает UTF-8 корректно.

## 19. Правила для следующей LLM/ассистента

1. Не читать и не раскрывать секреты из `.env`.
2. Перед изменениями изучать конкретные файлы, а не предполагать архитектуру.
3. Для ручных правок использовать `apply_patch`.
4. Не удалять SQLite-базы и отчеты без явного запроса.
5. Не откатывать чужие изменения в рабочем дереве.
6. После frontend-правок запускать `node --check spatialparse_site\app.js`.
7. После backend-правок запускать `python -m unittest tests.test_spatial_core`.
8. После изменений карты проверять в браузере `http://127.0.0.1:8001/site/demo.html`.
9. Для запросов на русском учитывать перевод, но не ломать русские примеры.
10. При работе с координатами помнить: backend использует `[lon, lat]`, Leaflet требует `[lat, lon]`.

## 20. Полезные примеры запросов

```text
Середина между Осиново и Юдино
Середина между Высокой Горой и Дербышками
5 км к северо-востоку от Казанского Кремля
10 км на юг от аэропорта Казань
15 км по направлению к Иннополису от центра Казани
Точка в трети пути от Зеленодольска до Казани
2 км к западу от Иннополиса
В окрестностях Казанского Кремля
Внутри парка Горького в Казани
Пересечение улицы Баумана и Профсоюзной в Казани
```

## 21. Минимальный mental model проекта

```text
Text query
  -> LLM parser
  -> spatial steps JSON
  -> geo_engine execution
  -> coordinates, centroid, optional road/reference geometry
  -> WebSocket events
  -> Leaflet rendering
  -> optional save/export
```

Самая важная часть качества - правильная интерпретация текста в `llm_parser.py` и правильный выбор географического контекста в `geo_engine.py`.

