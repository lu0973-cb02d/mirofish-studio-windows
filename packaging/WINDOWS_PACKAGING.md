# Windows 打包说明

MiroFish 提供两种 Electron-builder 产物：

- **控制面板版**：只包含桌面控制面板，默认连接已运行的 `http://127.0.0.1:3888/`。它适合已经有本地 MiroFish 环境的电脑，体积小，不携带 Python 虚拟环境、项目记录或配置。
- **全量安装版**：携带前端构建结果、Studio 服务、后端源代码和复制后的 Python 运行时与依赖，安装后可独立启动。首次启动时服务仍只监听本机回环地址；用户数据写入 `%APPDATA%\mirofish-studio-desktop\data`。

## 构建

在仓库根目录执行：

```powershell
npm install
npm run build:windows:control
npm run build:windows:full
# 或一次构建两版
npm run build:windows
```

也可以只生成 staging 目录并检查体积：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-windows.ps1 -Variant both -SkipBuild
```

构建脚本会主动排除 `.env`、日志、数据库、上传记录、备份压缩包、`__pycache__` 和 `.pyc`；不会读取或打包真实密钥与用户记录。全量版需要先存在 `backend/.venv`，否则脚本会停止并给出原因。

## 验收清单

1. `dist-installers/panel` 与 `dist-installers/full` 中分别存在 NSIS 安装程序和 portable 程序。
2. 安装后启动全量版，浏览器内置窗口能打开 Studio 首页，`http://127.0.0.1:3888/studio-health` 返回 200。
3. 控制面板版在已有服务运行时能打开；服务未运行时应显示可读的启动错误。
4. 安装目录和 staging 中不存在 `.env`、API key、Cookie、上传记录、`studio_data` 或 `record_backups`。
5. 在无真实密钥的环境中只验证启动和健康检查；LLM 调用、真实项目导入和用户数据迁移需另行验收。

构建输出未签名。正式发布前需要在受控发布环境中加入代码签名和杀毒误报检查。
