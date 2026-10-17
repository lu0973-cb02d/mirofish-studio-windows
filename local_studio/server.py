"""Single-origin local workbench, configuration API and owned engine proxy."""
from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from pathlib import Path

import httpx
from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.serving import make_server

from . import records as records_routes
from . import routes_config, routes_engine
from .config_store import ConfigStore
from .context import Context
from .core_update import CoreStore
from .engine import EngineError, EngineManager
from .records import record_inventory

VERSION = "1.1.0"


def create_app(root=None, store=None, engine=None, port=3888, core=None, core_source=None):
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    data_root = Path(os.environ.get("MIROFISH_DATA_ROOT", root)).resolve()
    store = store or ConfigStore(data_root)
    core = core or CoreStore(data_root, root)
    engine = engine or EngineManager(root, store, data_root=data_root, core=core)
    started = time.time()
    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False
    app.config["MAX_CONTENT_LENGTH"] = 55 * 1024 * 1024
    app.config["STUDIO_STORE"] = store
    app.config["STUDIO_ENGINE"] = engine
    app.config["STUDIO_CORE"] = core
    from .autobackup import AutoBackup
    app.config["STUDIO_AUTOBACKUP"] = AutoBackup(data_root)
    app.config["STUDIO_DATA_ROOT"] = data_root
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{x}" for x in allowed_hosts}

    def ok(data=None):
        return jsonify(success=True, data=data)

    def payload():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError("请提交有效的配置内容。")
        return value

    @app.before_request
    def local_boundary():
        if request.host not in allowed_hosts:
            return jsonify(success=False, error="请通过本地工作台地址访问。"), 403
        origin = request.headers.get("Origin")
        if origin and origin not in allowed_origins:
            return jsonify(success=False, error="不允许其他网站访问本地配置。"), 403
        if request.path.startswith("/studio-api/"):
            if request.headers.get("X-MiroFish-Studio") != "1":
                return jsonify(success=False, error="请从工作台操作。"), 403
            limit = 160 * 1024 * 1024 if request.path == "/studio-api/core/import" else 1024 * 1024
            if request.content_length and request.content_length > limit:
                return jsonify(success=False, error="请求内容过大。"), 413
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.path.startswith("/api/"):
            if request.headers.get("X-MiroFish-Studio") != "1":
                return jsonify(success=False, error="请从工作台操作。"), 403

    @app.after_request
    def privacy_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.path.startswith(("/studio-api/", "/api/")):
            response.headers["Cache-Control"] = "no-store"
            if response.is_json:
                from .redaction import redact_payload
                data = response.get_json()
                error_response = response.status_code >= 400 or (isinstance(data, dict) and data.get("success") is False)
                response.set_data(app.json.dumps(redact_payload(data, root=root,
                    extra_secrets=(getattr(engine, "token", ""),), strip_sensitive_fields=error_response)))
        return response

    @app.errorhandler(Exception)
    def safe_error(error):
        if isinstance(error, HTTPException):
            return jsonify(success=False, error="请求无效或页面不存在。"), error.code
        if isinstance(error, (ValueError, EngineError)):
            return jsonify(success=False, error=str(error)), 409 if isinstance(error, EngineError) else 400
        # Exception/provider bodies can contain credentials and are never sent
        # to the browser or a plaintext diagnostic log.
        logging.getLogger("studio").error("Operation failed: %s", type(error).__name__)
        return jsonify(success=False, error="操作未完成，请检查配置或稍后重试。"), 500

    from .core_routes import create_blueprint as create_core_blueprint
    app.register_blueprint(create_core_blueprint(core, engine, data_root, source=core_source))
    context = Context(app=app, root=root, data_root=data_root, store=store, engine=engine, ok=ok, payload=payload)
    for module in (routes_config, routes_engine, records_routes):
        app.register_blueprint(module.create_blueprint(context))

    @app.get("/studio-health")
    def health():
        return jsonify(service="MiroFish Studio", version=VERSION)

    @app.get("/studio-api/status")
    def status():
        cfg = store.public()
        state = engine.status()
        records = record_inventory(data_root)
        current = next((m for m in cfg["models"] if m["id"] == cfg["active_model_id"]), {})
        current_zep = next((m for m in cfg["zep"] if m["id"] == cfg["active_zep_id"]), {})
        pool_health = {}
        try:
            from .zep_pool import get_health
            pool_health = get_health(data_root)
        except (ImportError, OSError, ValueError):
            pass
        return ok({"version": VERSION, "engine": state,
            "counts": {k: len(v) for k, v in records.items()},
            "active_model": {k: current.get(k, "") for k in ("name", "model", "base_url")},
            "zep": {"active_name": current_zep.get("name", "未配置"), "auto_rotate": cfg["auto_zep"],
                    "available": sum(bool(z.get("enabled") and z.get("has_key")) for z in cfg["zep"]),
                    "total": len(cfg["zep"]), "health": pool_health},
            "busy": state.get("busy", False), "uptime_seconds": int(time.time() - started),
            "automatic_backup": app.config["STUDIO_AUTOBACKUP"].status(),
            "paths": {"data": str(data_root / "backend/uploads"), "backups": str(data_root / "record_backups")}})

    @app.route("/api/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    def proxy(path):
        if not engine.status().get("healthy"):
            return jsonify(success=False, error="推演引擎尚未就绪，请返回工作台启动。"), 503
        # Configuration changes and request submission share one gate. It is
        # held until the engine has accepted a background task into TaskManager.
        with engine.lock:
            engine.ensure_config_current()
            try:
                upstream = engine.request(request.method, "/api/" + path,
                    params=list(request.args.items(multi=True)), content=request.get_data(),
                    headers={k: v for k, v in request.headers if k.lower() in
                             {"content-type", "accept", "accept-language"}}, timeout=300)
            except httpx.HTTPError:
                return jsonify(success=False, error="引擎暂时没有响应。已提交的任务可能仍在运行，请先查看进度，不要重复提交。"), 502
        headers = {k: v for k, v in upstream.headers.items() if k.lower() in
                   {"content-type", "content-disposition"}}
        return Response(upstream.content, status=upstream.status_code, headers=headers)

    @app.get("/")
    @app.get("/<path:path>")
    def frontend(path=""):
        # A control-panel installer can carry the UI separately while using
        # an existing MiroFish source directory for records and the engine.
        # Keep the source-tree path as the default for development/full builds.
        # A verified core update brings the UI that matches its backend.
        core_dist = core.selection().frontend_root
        dist = (core_dist or Path(os.environ.get("MIROFISH_STUDIO_FRONTEND_ROOT", root / "frontend/dist"))).resolve()
        candidate = (dist / path).resolve()
        if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
            return send_from_directory(dist, path)
        if path.startswith(("studio-api/", "api/")):
            return jsonify(success=False, error="接口不存在。"), 404
        if not (dist / "index.html").is_file():
            return "工作台界面尚未构建，请运行安装修复。", 503
        return send_from_directory(dist, "index.html")

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=3888)
    parser.add_argument("--no-auto-start", action="store_true")
    args = parser.parse_args()
    app = create_app(port=args.port)
    server = make_server("127.0.0.1", args.port, app, threaded=True)
    app.config["STUDIO_SHUTDOWN"] = server.shutdown
    if not args.no_auto_start:
        def auto_start():
            try:
                app.config["STUDIO_ENGINE"].start()
            except Exception as error:
                logging.getLogger("studio").info("Auto-start deferred: %s", type(error).__name__)
        threading.Thread(target=auto_start, daemon=True).start()
    automatic_backup = app.config["STUDIO_AUTOBACKUP"]
    automatic_backup.start()
    try:
        server.serve_forever()
    finally:
        automatic_backup.stop()


if __name__ == "__main__":
    main()
