#!/usr/bin/env python3
import base64
import json
import mimetypes
import os
import re
import sqlite3
import warnings
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import URLError
from urllib.parse import unquote, urlparse


warnings.filterwarnings("ignore", category=DeprecationWarning)
import cgi


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
SCRINS_DIR = ROOT_DIR / "scrins"
UPLOADS_DIR = ROOT_DIR / "uploads"
DB_PATH = ROOT_DIR / "data" / "runforfan.sqlite"

MAX_TOTAL_UPLOAD_BYTES = 40 * 1024 * 1024
MAX_FILE_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def row_to_dict(row):
    return {key: row[key] for key in row.keys()}


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_int(value):
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    text = str(value).strip()
    if re.match(r"^\d{1,2}:\d{2}:\d{2}$", text):
        hours, minutes, seconds = [int(part) for part in text.split(":")]
        return hours * 3600 + minutes * 60 + seconds
    if re.match(r"^\d{1,2}:\d{2}$", text):
        minutes, seconds = [int(part) for part in text.split(":")]
        return minutes * 60 + seconds
    if "'" in text:
        minutes, seconds = re.findall(r"\d+", text)[:2]
        return int(minutes) * 60 + int(seconds)
    return int(float(text.replace(",", ".")))


def parse_float(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).strip().replace(",", "."))


def get_activities():
    with connect_db() as conn:
        activities = [
            row_to_dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM training_activities
                ORDER BY COALESCE(started_at, created_at) DESC, id DESC
                """
            )
        ]

        for activity in activities:
            activity_id = activity["id"]
            activity["segments"] = [
                row_to_dict(row)
                for row in conn.execute(
                    """
                    SELECT id, activity_id, segment_index, distance_km, duration_seconds,
                           pace_seconds_per_km, average_heart_rate_bpm, average_cadence_spm
                    FROM activity_segments
                    WHERE activity_id = ?
                    ORDER BY segment_index ASC
                    """,
                    (activity_id,),
                )
            ]
            activity["split_blocks"] = [
                row_to_dict(row)
                for row in conn.execute(
                    """
                    SELECT id, activity_id, block_index, start_km, end_km, distance_km,
                           duration_seconds, cumulative_duration_seconds, notes
                    FROM activity_split_blocks
                    WHERE activity_id = ?
                    ORDER BY block_index ASC
                    """,
                    (activity_id,),
                )
            ]
            activity["screenshot_sources"] = [
                row_to_dict(row)
                for row in conn.execute(
                    """
                    SELECT s.id, s.file_path, s.screen_type, s.captured_at, s.notes
                    FROM screenshot_sources s
                    INNER JOIN activity_screenshot_sources link ON link.source_id = s.id
                    WHERE link.activity_id = ?
                    ORDER BY s.id ASC
                    """,
                    (activity_id,),
                )
            ]

        return activities


def get_lactate_thresholds():
    with connect_db() as conn:
        measurements = [
            row_to_dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM lactate_threshold_measurements
                ORDER BY COALESCE(measured_at, id) DESC, id DESC
                """
            )
        ]

        for measurement in measurements:
            source = conn.execute(
                """
                SELECT id, file_path, screen_type, captured_at, notes
                FROM screenshot_sources
                WHERE id = ?
                """,
                (measurement["source_id"],),
            ).fetchone()
            measurement["screenshot_source"] = row_to_dict(source) if source else None

        return measurements


def get_import_batches():
    with connect_db() as conn:
        batches = [
            row_to_dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM import_batches
                ORDER BY created_at DESC, id DESC
                LIMIT 30
                """
            )
        ]
        for batch in batches:
            batch["sources"] = [
                row_to_dict(row)
                for row in conn.execute(
                    """
                    SELECT s.id, s.file_path, s.screen_type, s.captured_at, s.notes
                    FROM screenshot_sources s
                    INNER JOIN import_batch_sources link ON link.source_id = s.id
                    WHERE link.batch_id = ?
                    ORDER BY s.id ASC
                    """,
                    (batch["id"],),
                )
            ]
        return batches


def get_goals():
    with connect_db() as conn:
        return [
            row_to_dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM running_goals
                ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, created_at DESC, id DESC
                """
            )
        ]


def create_goal(payload):
    title = str(payload.get("title", "")).strip()
    goal_type = str(payload.get("goal_type", "")).strip() or "custom"
    if not title:
        raise ValueError("Название цели обязательно")
    if goal_type not in {"monthly_distance", "workout_count", "longest_run", "race", "custom"}:
        raise ValueError("Неизвестный тип цели")

    target_value = parse_float(payload.get("target_value")) if payload.get("target_value") not in (None, "") else None
    with connect_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO running_goals (
              title, goal_type, target_value, unit, period_start, period_end, reason, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                title,
                goal_type,
                target_value,
                str(payload.get("unit", "")).strip() or None,
                str(payload.get("period_start", "")).strip() or None,
                str(payload.get("period_end", "")).strip() or None,
                str(payload.get("reason", "")).strip() or None,
                str(payload.get("status", "active")).strip() or "active",
            ),
        )
        conn.commit()
        goal_id = cursor.lastrowid
        return row_to_dict(conn.execute("SELECT * FROM running_goals WHERE id = ?", (goal_id,)).fetchone())


def delete_goal(goal_id):
    with connect_db() as conn:
        cursor = conn.execute("DELETE FROM running_goals WHERE id = ?", (goal_id,))
        conn.commit()
        return cursor.rowcount


def delete_activity(activity_id):
    with connect_db() as conn:
        cursor = conn.execute("DELETE FROM training_activities WHERE id = ?", (activity_id,))
        conn.commit()
        return cursor.rowcount


def safe_filename(filename):
    name = Path(filename or "screenshot.jpg").name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "screenshot.jpg"
    return stem[:120]


def is_allowed_image(filename, data):
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        return False
    if data.startswith(b"\xff\xd8\xff"):
        return suffix in {".jpg", ".jpeg"}
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return suffix == ".png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return suffix == ".webp"
    return False


def save_uploaded_files(form):
    fields = form["screenshots"] if "screenshots" in form else []
    if not isinstance(fields, list):
        fields = [fields]

    upload_dir = UPLOADS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved = []

    for field in fields:
        if not getattr(field, "filename", None):
            continue
        filename = safe_filename(field.filename)
        data = field.file.read(MAX_FILE_UPLOAD_BYTES + 1)
        if len(data) > MAX_FILE_UPLOAD_BYTES:
            raise ValueError(f"Файл {filename} больше лимита {MAX_FILE_UPLOAD_BYTES // (1024 * 1024)} МБ")
        if not is_allowed_image(filename, data):
            raise ValueError(f"Файл {filename} не похож на поддерживаемое изображение JPG/PNG/WebP")

        target = upload_dir / f"{uuid.uuid4().hex[:10]}-{filename}"
        target.write_bytes(data)
        saved.append({
            "absolute_path": target,
            "file_path": str(target.relative_to(ROOT_DIR)),
            "filename": filename,
        })

    if not saved:
        raise ValueError("Нужно выбрать хотя бы один скриншот")
    return saved


def create_import_batch(saved_files):
    with connect_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO import_batches (status, recognition_engine, recognition_message, updated_at)
            VALUES ('uploaded', 'pending', 'Скриншоты загружены, распознавание еще не выполнено.', CURRENT_TIMESTAMP)
            """
        )
        batch_id = cursor.lastrowid
        sources = []
        for item in saved_files:
            source_cursor = conn.execute(
                """
                INSERT INTO screenshot_sources (file_path, screen_type, captured_at, notes)
                VALUES (?, 'uploaded_screenshot', ?, ?)
                """,
                (item["file_path"], now_text(), f"Uploaded screenshot: {item['filename']}"),
            )
            source_id = source_cursor.lastrowid
            conn.execute(
                "INSERT INTO import_batch_sources (batch_id, source_id) VALUES (?, ?)",
                (batch_id, source_id),
            )
            sources.append({"id": source_id, **item})
        conn.commit()
    return batch_id, sources


def llm_prompt():
    return (
        "Ты извлекаешь структурированные данные беговой тренировки из русскоязычных скриншотов. "
        "Верни только JSON без markdown. Если это тренировка, используй схему: "
        "{\"activity\":{\"title\":\"Бег на улице\",\"started_at\":\"YYYY-MM-DD HH:MM:SS\","
        "\"distance_km\":number,\"duration_seconds\":number,\"calories_kcal\":number,"
        "\"average_pace_seconds_per_km\":number,\"fastest_pace_seconds_per_km\":number,"
        "\"average_speed_kmh\":number,\"average_cadence_spm\":number,\"average_stride_cm\":number,"
        "\"steps_count\":number,\"average_heart_rate_bpm\":number,\"elevation_gain_m\":number,"
        "\"elevation_loss_m\":number,\"aerobic_training_stress\":number,\"aerobic_training_effect\":string},"
        "\"segments\":[{\"segment_index\":number,\"distance_km\":number,\"duration_seconds\":number,"
        "\"pace_seconds_per_km\":number,\"average_heart_rate_bpm\":number,\"average_cadence_spm\":number}],"
        "\"split_blocks\":[{\"block_index\":number,\"start_km\":number,\"end_km\":number,"
        "\"distance_km\":number,\"duration_seconds\":number,\"cumulative_duration_seconds\":number}]} "
        "Если данных недостаточно для создания тренировки, верни {\"activity\":null,\"notes\":\"...\"}."
    )


def extract_json_object(text):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM не вернул JSON-объект")
    return json.loads(cleaned[start:end + 1])


def recognize_with_llm(sources):
    endpoint = os.getenv("RUNFORFAN_LLM_URL")
    model = os.getenv("RUNFORFAN_LLM_MODEL")
    api_key = os.getenv("RUNFORFAN_LLM_API_KEY")
    if not endpoint or not model:
        return {
            "status": "fallback_pending",
            "engine": "fallback",
            "message": "LLM не настроен. Укажите RUNFORFAN_LLM_URL и RUNFORFAN_LLM_MODEL, затем загрузите скрины снова.",
            "payload": None,
            "raw": None,
        }

    content = [{"type": "text", "text": llm_prompt()}]
    for source in sources[:6]:
        mime_type, _ = mimetypes.guess_type(source["absolute_path"].name)
        encoded = base64.b64encode(source["absolute_path"].read_bytes()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type or 'image/jpeg'};base64,{encoded}"}})

    request_payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urlrequest.Request(endpoint, data=json.dumps(request_payload).encode("utf-8"), headers=headers)
    try:
        with urlrequest.urlopen(req, timeout=int(os.getenv("RUNFORFAN_LLM_TIMEOUT", "45"))) as response:
            raw_response = response.read().decode("utf-8")
    except URLError as exc:
        return {
            "status": "fallback_pending",
            "engine": "fallback",
            "message": f"LLM недоступен: {exc}. Скрины сохранены для ручной обработки.",
            "payload": None,
            "raw": None,
        }

    response_json = json.loads(raw_response)
    content_text = response_json["choices"][0]["message"]["content"]
    payload = extract_json_object(content_text)
    return {
        "status": "recognized_candidate",
        "engine": f"llm:{model}",
        "message": "LLM вернул структурированный JSON.",
        "payload": payload,
        "raw": response_json,
    }


def insert_recognized_activity(payload, source_ids):
    activity = payload.get("activity") if isinstance(payload, dict) else None
    if not activity:
        return None

    distance_km = parse_float(activity.get("distance_km"))
    duration_seconds = parse_int(activity.get("duration_seconds"))
    average_pace = parse_int(activity.get("average_pace_seconds_per_km"))
    if not distance_km or not duration_seconds or not average_pace:
        return None

    with connect_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO training_activities (
              activity_type, title, started_at, distance_km, duration_seconds, calories_kcal,
              average_pace_seconds_per_km, fastest_pace_seconds_per_km, average_speed_kmh,
              average_cadence_spm, average_stride_cm, steps_count, average_heart_rate_bpm,
              elevation_gain_m, elevation_loss_m, aerobic_training_stress, aerobic_training_effect, source_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "outdoor_run",
                activity.get("title") or "Бег на улице",
                activity.get("started_at"),
                distance_km,
                duration_seconds,
                parse_int(activity.get("calories_kcal")),
                average_pace,
                parse_int(activity.get("fastest_pace_seconds_per_km")),
                parse_float(activity.get("average_speed_kmh")),
                parse_int(activity.get("average_cadence_spm")),
                parse_int(activity.get("average_stride_cm")),
                parse_int(activity.get("steps_count")),
                parse_int(activity.get("average_heart_rate_bpm")),
                parse_float(activity.get("elevation_gain_m")),
                parse_float(activity.get("elevation_loss_m")),
                parse_float(activity.get("aerobic_training_stress")),
                activity.get("aerobic_training_effect"),
                "Data extracted by LLM from uploaded screenshots.",
            ),
        )
        activity_id = cursor.lastrowid

        for source_id in source_ids:
            conn.execute(
                "INSERT OR IGNORE INTO activity_screenshot_sources (activity_id, source_id) VALUES (?, ?)",
                (activity_id, source_id),
            )

        for segment in payload.get("segments") or []:
            conn.execute(
                """
                INSERT INTO activity_segments (
                  activity_id, segment_index, distance_km, duration_seconds, pace_seconds_per_km,
                  average_heart_rate_bpm, average_cadence_spm
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    activity_id,
                    parse_int(segment.get("segment_index")),
                    parse_float(segment.get("distance_km")),
                    parse_int(segment.get("duration_seconds")),
                    parse_int(segment.get("pace_seconds_per_km")),
                    parse_int(segment.get("average_heart_rate_bpm")),
                    parse_int(segment.get("average_cadence_spm")),
                ),
            )

        for block in payload.get("split_blocks") or []:
            conn.execute(
                """
                INSERT INTO activity_split_blocks (
                  activity_id, block_index, start_km, end_km, distance_km,
                  duration_seconds, cumulative_duration_seconds, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    activity_id,
                    parse_int(block.get("block_index")),
                    parse_float(block.get("start_km")),
                    parse_float(block.get("end_km")),
                    parse_float(block.get("distance_km")),
                    parse_int(block.get("duration_seconds")),
                    parse_int(block.get("cumulative_duration_seconds")),
                    "Split block extracted by LLM.",
                ),
            )

        conn.commit()
        return activity_id


def update_import_batch(batch_id, recognition, created_activity_id=None):
    with connect_db() as conn:
        conn.execute(
            """
            UPDATE import_batches
            SET status = ?, recognition_engine = ?, recognition_message = ?, raw_result_json = ?,
                created_activity_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                "recognized" if created_activity_id else recognition["status"],
                recognition["engine"],
                recognition["message"],
                json.dumps(recognition.get("raw") or recognition.get("payload"), ensure_ascii=False) if (recognition.get("raw") or recognition.get("payload")) else None,
                created_activity_id,
                batch_id,
            ),
        )
        conn.commit()


class RunforfanHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        try:
            if path in ("/", "/activities"):
                self.serve_file(STATIC_DIR / "index.html")
            elif path in ("/activity", "/activity.html"):
                self.serve_file(STATIC_DIR / "activity.html")
            elif path in ("/import", "/import.html"):
                self.serve_file(STATIC_DIR / "import.html")
            elif path in ("/analytics", "/analytics.html"):
                self.serve_file(STATIC_DIR / "analytics.html")
            elif path in ("/goals", "/goals.html"):
                self.serve_file(STATIC_DIR / "goals.html")
            elif path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            elif path == "/api/activities":
                self.serve_json(get_activities())
            elif path == "/api/lactate-thresholds":
                self.serve_json(get_lactate_thresholds())
            elif path == "/api/import-batches":
                self.serve_json(get_import_batches())
            elif path == "/api/goals":
                self.serve_json(get_goals())
            elif path.startswith("/static/"):
                self.serve_under_root(STATIC_DIR, path.removeprefix("/static/"))
            elif path.startswith("/scrins/"):
                self.serve_under_root(SCRINS_DIR, path.removeprefix("/scrins/"))
            elif path.startswith("/uploads/"):
                self.serve_under_root(UPLOADS_DIR, path.removeprefix("/uploads/"))
            else:
                self.send_error(404, "Not found")
        except sqlite3.Error as exc:
            self.serve_json({"error": f"Database error: {exc}"}, status=500)
        except OSError as exc:
            self.send_error(404, str(exc))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == "/api/goals":
                self.serve_json(create_goal(self.read_json_body()), status=201)
            elif path == "/api/import-screenshots":
                self.handle_import_screenshots()
            else:
                self.send_error(404, "Not found")
        except ValueError as exc:
            self.serve_json({"error": str(exc)}, status=400)
        except sqlite3.Error as exc:
            self.serve_json({"error": f"Database error: {exc}"}, status=500)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path.startswith("/api/activities/"):
                activity_id = int(path.removeprefix("/api/activities/"))
                deleted = delete_activity(activity_id)
                if not deleted:
                    self.serve_json({"error": "Тренировка не найдена"}, status=404)
                else:
                    self.serve_json({"deleted": True, "id": activity_id})
            elif path.startswith("/api/goals/"):
                goal_id = int(path.removeprefix("/api/goals/"))
                deleted = delete_goal(goal_id)
                if not deleted:
                    self.serve_json({"error": "Цель не найдена"}, status=404)
                else:
                    self.serve_json({"deleted": True, "id": goal_id})
            else:
                self.send_error(404, "Not found")
        except ValueError:
            self.serve_json({"error": "Некорректный идентификатор"}, status=400)
        except sqlite3.Error as exc:
            self.serve_json({"error": f"Database error: {exc}"}, status=500)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            raise ValueError("JSON-запрос слишком большой")
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8") or "{}")

    def handle_import_screenshots(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_TOTAL_UPLOAD_BYTES:
            raise ValueError(f"Загрузка больше лимита {MAX_TOTAL_UPLOAD_BYTES // (1024 * 1024)} МБ")
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            raise ValueError("Ожидается multipart/form-data")

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type},
        )
        saved_files = save_uploaded_files(form)
        batch_id, sources = create_import_batch(saved_files)

        try:
            recognition = recognize_with_llm(sources)
            created_activity_id = None
            if recognition.get("payload"):
                created_activity_id = insert_recognized_activity(recognition["payload"], [source["id"] for source in sources])
                if created_activity_id:
                    recognition["message"] = "Тренировка распознана LLM и добавлена в базу."
                else:
                    recognition["status"] = "fallback_pending"
                    recognition["message"] = "LLM ответил, но данных недостаточно для безопасного создания тренировки. Скрины сохранены."
            update_import_batch(batch_id, recognition, created_activity_id)
        except Exception as exc:
            recognition = {
                "status": "fallback_pending",
                "engine": "fallback",
                "message": f"Распознавание не удалось: {exc}. Скрины сохранены для ручной обработки.",
                "payload": None,
                "raw": None,
            }
            created_activity_id = None
            update_import_batch(batch_id, recognition, None)

        self.serve_json({
            "batch_id": batch_id,
            "status": "recognized" if created_activity_id else recognition["status"],
            "message": recognition["message"],
            "recognition_engine": recognition["engine"],
            "created_activity_id": created_activity_id,
            "sources": [{"id": source["id"], "file_path": source["file_path"]} for source in sources],
        }, status=201)

    def serve_under_root(self, root, relative_path):
        target = (root / relative_path).resolve()
        root = root.resolve()
        if root not in target.parents and target != root:
            self.send_error(403, "Forbidden")
            return
        self.serve_file(target)

    def serve_file(self, path):
        if not path.is_file():
            self.send_error(404, "File not found")
            return

        content_type, _ = mimetypes.guess_type(path.name)
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        with path.open("rb") as file:
            self.wfile.write(file.read())

    def serve_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def main():
    UPLOADS_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 8000), RunforfanHandler)
    print("Runforfan server: http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
