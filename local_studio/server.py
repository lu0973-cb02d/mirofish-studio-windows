"""Single-origin local workbench, configuration API and owned engine proxy."""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.serving import make_server

from .config_store import ConfigStore
from . import connectivity
from .engine import ConfigApplyUncertain, EngineError, EngineManager

VERSION = "1.1.0"


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def record_inventory(root):
    uploads = root / "backend/uploads"
    projects, simulations, reports = [], [], []
    for path in sorted((uploads / "projects").glob("*/project.json"), reverse=True):
        data = read_json(path)
        if data:
            projects.append({k: data.get(k) for k in
                ("project_id", "name", "status", "created_at", "updated_at")})
    # Current upstream calls the project metadata file project.json; also
    # tolerate metadata.json from older portable builds.
    if not projects:
        for path in (uploads / "projects").glob("*/meta.json"):
            data = read_json(path)
            if data:
                projects.append({k: data.get(k) for k in
                    ("project_id", "name", "status", "created_at", "updated_at")})
    for path in (uploads / "simulations").glob("*/state.json"):
        data = read_json(path)
        run = read_json(path.parent / "run_state.json")
        if data:
            simulations.append({"simulation_id": data.get("simulation_id", path.parent.name),
                "project_id": data.get("project_id"), "status": run.get("runner_status", data.get("status")),
                "run_status": run.get("runner_status"),
                "created_at": data.get("created_at"), "current_round": run.get("current_round", 0),
                "total_rounds": run.get("total_rounds", 0), "completed_at": run.get("completed_at")})
    for path in (uploads / "reports").glob("*/meta.json"):
        data = read_json(path)
        if data:
            reports.append({k: data.get(k) for k in
                ("report_id", "simulation_id", "status", "created_at", "title")})
    for project in projects:
        matching = [s for s in simulations if s["project_id"] == project["project_id"]]
        if matching:
            sim = max(matching, key=lambda s: s.get("created_at") or "")
            project["simulation_id"] = sim["simulation_id"]
            project["simulation_status"] = sim["status"]
            project["simulation_run_status"] = sim.get("run_status")
            matches = [r for r in reports if r["simulation_id"] == sim["simulation_id"]]
            if matches:
                latest_report = max(matches, key=lambda r: r.get("created_at") or "")
                project["report_id"] = latest_report["report_id"]
                project["report_status"] = latest_report.get("status")
    projects.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return {"projects": projects, "simulations": simulations, "reports": reports}


def create_app(root=None, store=None, engine=None, port=3888):
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    data_root = Path(os.environ.get("MIROFISH_DATA_ROOT", root)).resolve()
    store = store or ConfigStore(data_root)
    engine = engine or EngineManager(root, store, data_root=data_root)
    started = time.time()
    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False
    app.config["MAX_CONTENT_LENGTH"] = 55 * 1024 * 1024
    app.config["STUDIO_STORE"] = store
    app.config["STUDIO_ENGINE"] = engine
    from .autobackup import AutoBackup
    app.config["STUDIO_AUTOBACKUP"] = AutoBackup(data_root)
    app.config["STUDIO_DATA_ROOT"] = data_root
    backup_lock = threading.Lock()
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
            if request.content_length and request.content_length > 1024 * 1024:
                return jsonify(success=False, error="配置请求过大。"), 413
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

    @app.get("/studio-health")
    def health():
        return jsonify(service="MiroFish Studio", version=VERSION)

    @app.get("/studio-api/config")
    def config():
        return ok(store.public())

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

    @app.post("/studio-api/models")
    def save_model():
        data = payload()
        with engine.lock:
            active_edit = bool(data.get("id") and data["id"] == store.public()["active_model_id"])
            if active_edit:
                engine.ensure_idle()
            before = store._snapshot()
            try:
                result = store.save_model(data)
                if active_edit and engine.status().get("healthy"):
                    engine.model_snapshot()
                    engine.apply_config()
            except ConfigApplyUncertain:
                raise
            except Exception:
                store._restore(before)
                raise
            return ok(result)

    @app.delete("/studio-api/models/<identifier>")
    def delete_model(identifier):
        with engine.lock:
            if identifier == store.public()["active_model_id"] and engine.status().get("healthy"):
                raise EngineError("当前模型正被引擎使用，请先切换预设或停止引擎。")
            return ok(store.delete_model(identifier))

    @app.post("/studio-api/models/<identifier>/activate")
    def activate_model(identifier):
        with engine.lock:
            engine.ensure_idle()
            before = store._snapshot()
            try:
                result = store.activate_model(identifier)
                engine.model_snapshot()
                engine.apply_config()
            except ConfigApplyUncertain:
                raise
            except Exception:
                store._restore(before)
                raise
            return ok(result)

    def model_draft():
        data = payload()
        profile = store.runtime_model(data["id"]) if data.get("id") else {}
        for field in ("base_url", "model", "name"):
            if field in data:
                profile[field] = data[field]
        if data.get("key"):
            profile["key"] = data["key"]
        return profile

    @app.post("/studio-api/models/discover")
    def discover_models():
        return ok(connectivity.discover_models(model_draft()))

    @app.post("/studio-api/models/test")
    def test_model():
        return ok(connectivity.test_model(model_draft()))

    @app.post("/studio-api/zep")
    def save_zep():
        data = payload()
        with engine.lock:
            # The Zep pool reloads saved connections, so updates to existing
            # credentials wait until background work has finished.
            if data.get("id"):
                engine.ensure_idle()
            before = store._snapshot()
            try:
                result = store.save_zep(data)
                if data.get("id") == before["active_zep_id"] and engine.status().get("healthy"):
                    engine.apply_config()
            except ConfigApplyUncertain:
                raise
            except Exception:
                store._restore(before)
                raise
            return ok(result)

    @app.delete("/studio-api/zep/<identifier>")
    def delete_zep(identifier):
        with engine.lock:
            if engine.status().get("healthy"):
                raise EngineError("删除 Zep 连接前请停止引擎，以免影响已有图谱。可先将它停用。")
            return ok(store.delete_zep(identifier))

    @app.post("/studio-api/zep/<identifier>/activate")
    def activate_zep(identifier):
        with engine.lock:
            engine.ensure_idle()
            before = store._snapshot()
            try:
                result = store.activate_zep(identifier)
                engine.apply_config()
            except ConfigApplyUncertain:
                raise
            except Exception:
                store._restore(before)
                raise
            return ok(result)

    @app.post("/studio-api/zep/test")
    def test_zep():
        data = payload()
        profile = store.runtime_zep(data["id"]) if data.get("id") else {}
        if data.get("key"):
            profile["key"] = data["key"]
        return ok(connectivity.test_zep(profile))

    @app.post("/studio-api/settings")
    def settings():
        value = payload().get("auto_zep")
        if not isinstance(value, bool):
            raise ValueError("自动轮换设置无效。")
        with engine.lock:
            store.set_auto_zep(value)
        return ok(store.public())

    @app.post("/studio-api/engine/<action>")
    def engine_action(action):
        if action == "start":
            return ok(engine.start())
        if action == "stop":
            return ok(engine.stop())
        if action == "restart":
            with engine.lock:
                engine.stop()
                return ok(engine.start())
        raise ValueError("未知引擎操作。")

    @app.post("/studio-api/quit")
    def quit_studio():
        shutdown = app.config.get("STUDIO_SHUTDOWN")
        if shutdown is None:
            raise EngineError("当前启动方式不支持退出，请先停止引擎。")
        engine.stop()
        def finish():
            app.config["STUDIO_AUTOBACKUP"].stop()
            shutdown()
        threading.Thread(target=finish, daemon=True).start()
        return ok({"message": "工作台已退出，配置与记录已保留。再次使用时双击桌面入口。"})

    @app.get("/studio-api/records")
    def records():
        return ok(record_inventory(data_root))

    @app.get("/studio-api/backups")
    def backups():
        import record_backup
        return ok([{"name": p.name, "size": p.stat().st_size,
                    "created_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat()}
                   for p in record_backup.list_backups(root=data_root)])

    @app.post("/studio-api/backups/create")
    def backup_create():
        import record_backup
        with backup_lock:
            path = record_backup.create_backup(root=data_root)
            manifest = record_backup.verify_backup(path)
            return ok({"name": path.name, "file_count": manifest["file_count"],
                       "message": "备份已创建并通过完整性校验。"})

    @app.post("/studio-api/backups/restore")
    def backup_restore():
        import record_backup
        data = payload()
        name = data.get("name", "")
        if not isinstance(name, str) or not re.fullmatch(r"records-[\w-]+\.zip", name):
            raise ValueError("请选择工作台中的有效备份。")
        with engine.lock, backup_lock:
            state = engine.status()
            if state.get("state") != "stopped" or state.get("healthy") or state.get("owned"):
                raise EngineError("请先停止引擎，再恢复记录。")
            path = (data_root / "record_backups" / name).resolve()
            if path.parent != (data_root / "record_backups").resolve() or not path.is_file():
                raise ValueError("备份不存在。")
            record_backup.verify_backup(path)
            before = record_backup.create_backup("pre-restore", root=data_root)
            manifest, _ = record_backup.restore_backup(path, root=data_root)
            return ok({"file_count": manifest["file_count"], "previous_backup": before.name,
                "restore_notes": manifest.get("restore_notes", []),
                "missing_zep_profile_ids": manifest.get("missing_zep_profile_ids", []),
                "zep_bindings_restored": manifest.get("zep_bindings_restored", False),
                "message": "本地记录已恢复，恢复前的记录已另行备份。云端图谱仍需原 Zep 连接；中断的推演不会自动续跑。"})

    @app.get("/studio-api/logs")
    def logs():
        # Show operational lines only, never model prompts, provider responses,
        # authentication headers or arbitrary backend log tails.
        lines = []
        log_path = data_root / "studio_data/engine.log"
        if log_path.exists():
            with log_path.open("rb") as f:
                f.seek(max(0, log_path.stat().st_size - 64000))
                text = f.read().decode("utf-8", errors="replace")
            for line in text.splitlines():
                match = re.search(r'"(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD) [^\r\n]* HTTP/1\.[01]" (\d{3})', line)
                if match:
                    lines.append(f"{match.group(1)} 请求 · HTTP {match.group(2)}")
                elif "启动完成" in line or "MiroFish Backend" in line:
                    lines.append("推演引擎已启动")
                elif "采访环境仍可用" in line:
                    lines.append("推演已结束，采访环境保留中")
        return ok({"lines": lines[-70:]})

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
        dist = Path(os.environ.get("MIROFISH_STUDIO_FRONTEND_ROOT", root / "frontend/dist")).resolve()
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
