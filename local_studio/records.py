"""Local records, record backups and the operational log."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path

from flask import Blueprint

from .engine import EngineError


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


def create_blueprint(ctx):
    bp = Blueprint('records', __name__)
    data_root, engine, ok, payload = ctx.data_root, ctx.engine, ctx.ok, ctx.payload
    backup_lock = threading.Lock()

    @bp.get("/studio-api/records")
    def records():
        return ok(record_inventory(data_root))

    @bp.get("/studio-api/backups")
    def backups():
        import record_backup
        return ok([{"name": p.name, "size": p.stat().st_size,
                    "created_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat()}
                   for p in record_backup.list_backups(root=data_root)])

    @bp.post("/studio-api/backups/create")
    def backup_create():
        import record_backup
        with backup_lock:
            path = record_backup.create_backup(root=data_root)
            manifest = record_backup.verify_backup(path)
            return ok({"name": path.name, "file_count": manifest["file_count"],
                       "message": "备份已创建并通过完整性校验。"})

    @bp.post("/studio-api/backups/restore")
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

    @bp.get("/studio-api/logs")
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

    return bp
