import hmac
import json
import logging
import os
import sys
import time
import uuid

from flask import Flask, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)

QUIET_PATHS = {"/health", "/ready", "/metrics"}


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload)


def configure_logging():
    logger = logging.getLogger("app")
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    logger.propagate = False
    return logger


def create_app():
    app = Flask(__name__)
    logger = configure_logging()
    items = []

    @app.before_request
    def start_timer():
        g.start = time.perf_counter()
        g.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    @app.after_request
    def record_request(response):
        duration = time.perf_counter() - g.start
        endpoint = request.url_rule.rule if request.url_rule else "unmatched"
        REQUEST_COUNT.labels(request.method, endpoint, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, endpoint).observe(duration)
        level = logging.DEBUG if request.path in QUIET_PATHS else logging.INFO
        if response.status_code >= 500:
            level = logging.ERROR
        logger.log(
            level,
            "request completed",
            extra={
                "fields": {
                    "request_id": g.request_id,
                    "method": request.method,
                    "path": request.path,
                    "status": response.status_code,
                    "duration_ms": round(duration * 1000, 2),
                }
            },
        )
        response.headers["X-Request-ID"] = g.request_id
        return response

    @app.get("/")
    def index():
        return jsonify(
            service="devops-platform-api",
            version=os.getenv("APP_VERSION", "1.0.0"),
            environment=os.getenv("APP_ENV", "local"),
        )

    @app.get("/health")
    def health():
        if os.getenv("BREAK_HEALTH", "false").lower() == "true":
            return jsonify(status="unhealthy"), 500
        return jsonify(status="ok")

    @app.get("/ready")
    def ready():
        if os.getenv("BREAK_HEALTH", "false").lower() == "true":
            return jsonify(status="not ready"), 503
        return jsonify(status="ready")

    @app.get("/metrics")
    def metrics():
        return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}

    @app.get("/api/items")
    def list_items():
        return jsonify(items=items, count=len(items))

    @app.post("/api/items")
    def create_item():
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        if not name:
            return jsonify(error="field 'name' is required"), 400
        item = {"id": len(items) + 1, "name": name}
        items.append(item)
        return jsonify(item), 201

    @app.get("/api/items/<int:item_id>")
    def get_item(item_id):
        for item in items:
            if item["id"] == item_id:
                return jsonify(item)
        return jsonify(error="item not found"), 404

    @app.get("/api/slow")
    def slow():
        ms = min(request.args.get("ms", default=500, type=int), 5000)
        time.sleep(ms / 1000)
        return jsonify(slept_ms=ms)

    @app.get("/api/error")
    def error():
        return jsonify(error="simulated server error"), 500

    @app.get("/api/protected")
    def protected():
        expected = os.getenv("API_KEY", "")
        provided = request.headers.get("X-API-Key", "")
        if not expected or not hmac.compare_digest(provided, expected):
            return jsonify(error="unauthorized"), 401
        return jsonify(message="secret data")

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))