"""Starting, stopping and quitting the local engine."""
from __future__ import annotations

import threading

from flask import Blueprint

from .engine import EngineError


def create_blueprint(ctx):
    bp = Blueprint('engine', __name__)
    app, engine, ok = ctx.app, ctx.engine, ctx.ok

    @bp.post("/studio-api/engine/<action>")
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

    @bp.post("/studio-api/quit")
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

    return bp
