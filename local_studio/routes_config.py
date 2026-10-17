"""Model presets, Zep connections and rotation settings."""
from __future__ import annotations


from flask import Blueprint

from . import connectivity
from .engine import ConfigApplyUncertain, EngineError


def create_blueprint(ctx):
    bp = Blueprint('config', __name__)
    store, engine, ok, payload = ctx.store, ctx.engine, ctx.ok, ctx.payload

    @bp.get("/studio-api/config")
    def config():
        return ok(store.public())

    @bp.post("/studio-api/models")
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

    @bp.delete("/studio-api/models/<identifier>")
    def delete_model(identifier):
        with engine.lock:
            if identifier == store.public()["active_model_id"] and engine.status().get("healthy"):
                raise EngineError("当前模型正被引擎使用，请先切换预设或停止引擎。")
            return ok(store.delete_model(identifier))

    @bp.post("/studio-api/models/<identifier>/activate")
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

    @bp.post("/studio-api/models/discover")
    def discover_models():
        return ok(connectivity.discover_models(model_draft()))

    @bp.post("/studio-api/models/test")
    def test_model():
        return ok(connectivity.test_model(model_draft()))

    @bp.post("/studio-api/zep")
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

    @bp.delete("/studio-api/zep/<identifier>")
    def delete_zep(identifier):
        with engine.lock:
            if engine.status().get("healthy"):
                raise EngineError("删除 Zep 连接前请停止引擎，以免影响已有图谱。可先将它停用。")
            return ok(store.delete_zep(identifier))

    @bp.post("/studio-api/zep/<identifier>/activate")
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

    @bp.post("/studio-api/zep/test")
    def test_zep():
        data = payload()
        profile = store.runtime_zep(data["id"]) if data.get("id") else {}
        if data.get("key"):
            profile["key"] = data["key"]
        return ok(connectivity.test_zep(profile))

    @bp.post("/studio-api/settings")
    def settings():
        value = payload().get("auto_zep")
        if not isinstance(value, bool):
            raise ValueError("自动轮换设置无效。")
        with engine.lock:
            store.set_auto_zep(value)
        return ok(store.public())

    return bp
