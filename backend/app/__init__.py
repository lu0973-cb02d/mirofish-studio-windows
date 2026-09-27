"""
MiroFish Backend - Flask应用工厂
"""

import os
import re
import secrets
import warnings

# 抑制 multiprocessing resource_tracker 的警告（来自第三方库如 transformers）
# 需要在所有其他导入之前设置
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request, jsonify
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger


def create_app(config_class=Config):
    """Flask应用工厂函数"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # 设置JSON编码：确保中文直接显示（而不是 \uXXXX 格式）
    # Flask >= 2.3 使用 app.json.ensure_ascii，旧版本使用 JSON_AS_ASCII 配置
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False
    
    # 设置日志
    logger = setup_logger('mirofish')
    
    # 只在 reloader 子进程中打印启动信息（避免 debug 模式下打印两次）
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process
    
    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish Backend 启动中...")
        logger.info("=" * 50)
    
    # 启用CORS
    if not os.environ.get('MIROFISH_STUDIO_ROOT'):
        CORS(app, resources={r"/api/*": {"origins": ["http://127.0.0.1:3000", "http://localhost:3000"]}})
    
    # 注册模拟进程清理函数（确保服务器关闭时终止所有模拟进程）
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("已注册模拟进程清理函数")
    
    # 请求日志中间件
    @app.before_request
    def log_request():
        if os.environ.get('MIROFISH_STUDIO_ROOT') and request.path.startswith('/api/'):
            expected = os.environ.get('MIROFISH_ENGINE_TOKEN', '')
            actual = request.headers.get('X-MiroFish-Engine-Token', '')
            if not expected or not secrets.compare_digest(actual, expected):
                return jsonify(success=False, error='请通过本地工作台访问。'), 403
        logger = get_logger('mirofish.request')
        logger.debug(f"请求: {request.method} {request.path}")
    
    @app.after_request
    def log_response(response):
        if os.environ.get('MIROFISH_STUDIO_ROOT') and response.is_json:
            try:
                from local_studio.redaction import redact_payload
                payload = response.get_json()
                failed = response.status_code >= 400 or (isinstance(payload, dict) and payload.get('success') is False)
                content = redact_payload(payload, root=os.environ['MIROFISH_STUDIO_ROOT'],
                                         strip_traceback=True, strip_sensitive_fields=failed)
                response.set_data(app.json.dumps(content))
            except Exception:
                # A failed safety pass must never release the original response.
                response.set_data(app.json.dumps({'success': False, 'error': '响应内容暂时无法安全显示，请稍后重试。'}))
                response.status_code = 500
        logger = get_logger('mirofish.request')
        logger.debug(f"响应: {response.status_code}")
        return response
    
    # 注册蓝图
    from .api import graph_bp, simulation_bp, report_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    
    # 健康检查
    @app.route('/health')
    def health():
        result = {'status': 'ok', 'service': 'MiroFish Backend',
                  'studio_instance': os.environ.get('MIROFISH_ENGINE_INSTANCE', '')}
        if os.environ.get('MIROFISH_STUDIO_ROOT'):
            from .studio_runtime import health_snapshot
            result.update(health_snapshot())
        return result

    @app.post('/api/studio/apply-config')
    def apply_studio_config():
        if not os.environ.get('MIROFISH_STUDIO_ROOT'):
            return jsonify(success=False, error='Studio 未启用'), 404
        from .studio_runtime import apply_selected_config
        content = request.get_json(silent=True)
        expected_revision = content.get('expected_revision') if isinstance(content, dict) else None
        if not isinstance(expected_revision, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_revision):
            return jsonify(success=False, error='请从工作台重新应用配置。',
                           code='CONFIG_NOT_APPLIED', applied=False), 409
        try:
            return jsonify(success=True, data=apply_selected_config(expected_revision=expected_revision))
        except ValueError as error:
            return jsonify(success=False, error=str(error), code='CONFIG_NOT_APPLIED',
                           applied=False, expected_revision=expected_revision), 409
    
    if should_log_startup:
        logger.info("MiroFish Backend 启动完成")
    
    return app
