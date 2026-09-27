"""Own and supervise only this installation's engine process."""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psutil


class EngineError(ValueError):
    pass


class ConfigApplyUncertain(EngineError):
    """The engine may have applied this selection; callers must not roll it back."""


class EngineManager:
    def __init__(self, root: Path, store, port=5001, data_root: Path | str | None = None):
        self.root = Path(root).resolve()
        self.data_root = Path(data_root or self.root).resolve()
        self.store = store
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.state_dir = self.data_root / "studio_data"
        self.state_dir.mkdir(exist_ok=True)
        self.manifest = self.state_dir / "engine.json"
        self.lock = threading.RLock()
        self.process = None
        self.token = ""
        self.instance = ""
        self.pid = None
        self.created = None
        self.log_handle = None
        self.message = "推演引擎尚未启动"
        self._adopt()

    def _python_path(self) -> Path:
        """Return the bundled interpreter or the development virtualenv."""
        candidates = (
            self.root / "runtime/python.exe",
            self.root / "backend/.venv/Scripts/python.exe",
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        return candidates[-1].resolve()

    def _adopt(self):
        try:
            data = json.loads(self.manifest.read_text(encoding="utf-8"))
            self.pid, self.created = data["pid"], data["created"]
            self.token, self.instance = data["token"], data["instance"]
            if not self._owned_process():
                self.pid = None
                self.token = self.instance = ""
        except (OSError, ValueError, KeyError):
            pass

    def _owned_process(self):
        if not self.pid:
            return None
        try:
            p = psutil.Process(self.pid)
            if abs(p.create_time() - self.created) > 0.01:
                return None
            command = p.cmdline()
            expected_python = self._python_path()
            expected_script = self.root / "backend/run.py"
            if not command or Path(command[0]).resolve() != expected_python:
                return None
            if not any(Path(arg).is_absolute() and Path(arg).resolve() == expected_script for arg in command[1:]):
                return None
            # Windows venv's redirector changes its own cwd to Temp while its
            # actual Python child correctly keeps backend as cwd. Exact binary,
            # script, creation time and the health instance prove ownership.
            return p
        except (psutil.Error, OSError, TypeError):
            return None

    def request(self, method, path, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers["X-MiroFish-Engine-Token"] = self.token
        # A loopback request must never travel through a user's proxy.
        with httpx.Client(timeout=kwargs.pop("timeout", 8), trust_env=False,
                          follow_redirects=False) as client:
            return client.request(method, self.url + path, headers=headers, **kwargs)

    def health(self):
        try:
            r = self.request("GET", "/health", timeout=0.8)
            data = r.json()
            if r.status_code == 200 and isinstance(data, dict) and data.get("service") == "MiroFish Backend":
                return data
        except (httpx.HTTPError, ValueError):
            pass
        return None

    def _port_in_use(self):
        try:
            with socket.socket() as probe:
                probe.settimeout(0.3)
                return probe.connect_ex(("127.0.0.1", self.port)) == 0
        except OSError:
            return True  # An unverifiable port is never safe to adopt or overwrite.

    def status(self):
        health = self.health()
        owned = self._owned_process() is not None
        matching = bool(owned and health and health.get("studio_instance") == self.instance)
        if (health and not matching) or (not health and not owned and self._port_in_use()):
            return {"state": "error", "healthy": False, "owned": False, "pid": None,
                    "configuration_synced": False,
                    "message": f"{self.port} 端口由其他程序或实例使用，请先关闭对应程序。"}
        if matching:
            try:
                selected_revision = self.store.runtime_revision()
            except (ValueError, OSError):
                selected_revision = ""
            runtime_revision = health.get("runtime_revision", "")
            synced = bool(runtime_revision and runtime_revision == selected_revision)
            return {"state": "running", "healthy": True, "owned": True, "pid": self.pid,
                    "message": "引擎运行正常" if synced else "所选配置尚未确认同步，请重新应用配置或重启引擎。",
                    "busy": health.get("busy", False), "configuration_synced": synced,
                    "runtime_revision": runtime_revision, "selected_revision": selected_revision,
                    "runtime_model_id": health.get("runtime_model_id"),
                    "interview_count": health.get("interview_count", 0)}
        return {"state": "starting" if owned else "stopped", "healthy": False,
                "owned": owned, "pid": self.pid if owned else None, "message": self.message,
                "configuration_synced": False}

    def ensure_config_current(self):
        """Gate new work until the running engine confirms the saved selection."""
        with self.lock:
            state = self.status()
            if not state.get("healthy"):
                raise EngineError("推演引擎尚未就绪，请先启动或检查引擎状态。")
            if not state.get("configuration_synced"):
                raise ConfigApplyUncertain("所选配置尚未确认同步，已暂停提交新任务。请重新应用配置或重启引擎。")
            return state

    def ensure_idle(self):
        state = self.status()
        if state["state"] == "error":
            raise EngineError(state["message"])
        if state.get("busy"):
            raise EngineError("当前有任务正在执行。可以先保存预设，任务结束后再切换或停止引擎。")
        if state.get("owned") and not state.get("healthy"):
            raise EngineError("引擎仍在启动或响应恢复中，请稍后再操作。")

    def model_snapshot(self):
        return self._validate_model(self.store.runtime_model())

    @staticmethod
    def _validate_model(model):
        if not model.get("model"):
            raise EngineError("请先在模型预设中选择一个模型。")
        if not model.get("key"):
            host = urlsplit(model["base_url"]).hostname
            if host not in {"localhost", "127.0.0.1", "::1"}:
                raise EngineError("当前模型预设缺少 API Key，请先填写并保存。")
            model["key"] = "local-no-key"
        return model

    def start(self):
        with self.lock:
            state = self.status()
            if state.get("healthy"):
                return state
            if state["state"] == "error":
                raise EngineError(state["message"])
            if self._owned_process():
                return state
            selected = self.store.runtime_selection()
            model = self._validate_model(selected["model"])
            zep = selected["zep"]
            if not zep.get("key"):
                raise EngineError("请先添加并启用一个 Zep 连接。")
            if self._port_in_use():
                raise EngineError(f"{self.port} 端口被占用，未停止或覆盖其他程序。")
            self.token, self.instance = secrets.token_urlsafe(32), secrets.token_hex(16)
            env = os.environ.copy()
            env.update({"MIROFISH_STUDIO_ROOT": str(self.data_root),
                        "MIROFISH_DATA_ROOT": str(self.data_root),
                        "MIROFISH_CODE_ROOT": str(self.root),
                        "MIROFISH_ENGINE_TOKEN": self.token,
                        "MIROFISH_ENGINE_INSTANCE": self.instance,
                        "MIROFISH_MODEL_ID": model["id"],
                        "MIROFISH_CONFIG_REVISION": selected["revision"],
                        "LLM_API_KEY": model["key"], "LLM_BASE_URL": model["base_url"],
                        "LLM_MODEL_NAME": model["model"], "ZEP_API_KEY": zep["key"],
                        "FLASK_DEBUG": "false", "FLASK_HOST": "127.0.0.1",
                        "FLASK_PORT": str(self.port), "PYTHONUTF8": "1",
                        "PYTHONIOENCODING": "utf-8"})
            env.pop("ZEP_API_URL", None)
            # Do not allow stale boost variables to silently override presets.
            for name in ("LLM_BOOST_API_KEY", "LLM_BOOST_BASE_URL", "LLM_BOOST_MODEL_NAME"):
                env.pop(name, None)
            env["PYTHONPATH"] = str(self.root) + os.pathsep + env.get("PYTHONPATH", "")
            python = self._python_path()
            if not python.exists():
                raise EngineError("缺少本地 Python 环境，请修复安装。")
            self.log_handle = (self.state_dir / "engine.log").open("a", encoding="utf-8")
            self.process = subprocess.Popen([str(python), str(self.root / "backend/run.py")],
                cwd=self.root / "backend", env=env, stdout=self.log_handle,
                stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.pid = self.process.pid
            self.created = psutil.Process(self.pid).create_time()
            temp = self.manifest.with_suffix(".tmp")
            temp.write_text(json.dumps({"pid": self.pid, "created": self.created,
                "token": self.token, "instance": self.instance}), encoding="utf-8")
            os.replace(temp, self.manifest)
            self.message = "引擎正在启动，请稍候"
            for _ in range(32):
                state = self.status()
                if state.get("healthy"):
                    return state
                if self.process.poll() is not None:
                    self.message = "引擎启动失败，请查看运行日志或检查配置。"
                    raise EngineError(self.message)
                time.sleep(0.25)
            return self.status()

    def apply_config(self):
        with self.lock:
            state = self.status()
            if not state.get("healthy"):
                if state.get("state") == "error":
                    raise EngineError("引擎端口由其他程序使用，本次配置未应用。")
                if state.get("owned"):
                    raise ConfigApplyUncertain("引擎暂时无响应，无法确认配置是否已应用。已保留所选配置，请重新应用或重启引擎。")
                return None  # A stopped engine reads the selected snapshot at start.
            target = self.store.runtime_revision()
            body, response_status = None, None
            try:
                response = self.request("POST", "/api/studio/apply-config",
                                        json={"expected_revision": target}, timeout=10)
                response_status = response.status_code
                body = response.json()
                result = body.get("data") if isinstance(body, dict) else None
                if (200 <= response_status < 300 and isinstance(body, dict) and body.get("success") is True
                        and isinstance(result, dict) and result.get("runtime_revision") == target):
                    return result
            except (httpx.HTTPError, ValueError, TypeError):
                # The response can disappear after the backend committed its
                # in-memory configuration. Never infer failure from a lost reply.
                pass
            health = self.health()
            if (isinstance(health, dict) and health.get("studio_instance") == self.instance
                    and health.get("runtime_revision") == target):
                return {"runtime_revision": target, "confirmed_by_health": True,
                        "message": "配置已应用，并通过引擎状态确认。"}
            rejected = (isinstance(body, dict) and response_status == 409
                        and body.get("success") is False and body.get("applied") is False
                        and body.get("code") == "CONFIG_NOT_APPLIED"
                        and body.get("expected_revision") == target)
            if rejected:
                raise EngineError("当前配置未能应用，任务可能仍在执行。请稍后重试。")
            raise ConfigApplyUncertain("配置请求的结果暂时无法确认。已保留所选配置并暂停新任务，请重新应用配置或重启引擎。")

    def stop(self):
        with self.lock:
            self.ensure_idle()
            p = self._owned_process()
            if p is None:
                return self.status()
            # Close completed OASIS interviews gracefully before releasing engine.
            health = self.health() or {}
            for simulation_id in health.get("interview_ids", []):
                try:
                    self.request("POST", "/api/simulation/close-env",
                                 json={"simulation_id": simulation_id, "timeout": 8}, timeout=12)
                except httpx.HTTPError:
                    raise EngineError("采访环境尚未正常关闭，请稍后重试停止。")
            children = p.children(recursive=True)
            # All targets are descendants of the verified installation process.
            for child in reversed(children):
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            p.terminate()
            _, alive = psutil.wait_procs(children + [p], timeout=5)
            for remaining in alive:
                remaining.kill()
            self.pid = None
            self.manifest.unlink(missing_ok=True)
            if self.log_handle:
                self.log_handle.close()
                self.log_handle = None
            self.message = "引擎已停止，配置与记录已保留"
            return self.status()
