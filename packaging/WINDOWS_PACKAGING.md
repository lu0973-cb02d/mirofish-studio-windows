# Windows 打包说明

## 选择安装包

- **Panel 控制面板版**：包含桌面窗口和工作台界面。需要已有的 Studio 兼容工作目录，其中包含 `local_studio/server.py`、`backend` 和已安装依赖的 Python 环境。首次启动可选择目录；服务未运行时会尝试启动。只有上游 MiroFish 源码、没有本改版 Studio 层的目录不能直接使用。
- **Full 全量版**：包含桌面端、Studio、MiroFish 源码、构建后的界面，以及独立 Python 运行时和依赖。Windows x64 目标电脑无需另装 Node.js、Python 或 uv；首次使用仍需配置自己的模型与 Zep 连接。

两版都只通过本机 `127.0.0.1:3888` 提供工作台。全量版把用户数据保存在 `%APPDATA%\mirofish-studio-desktop\data`，不写回安装资源目录。

## 本地构建

在 Windows x64 上准备 Node.js 22、Python 3.11 x64 和 uv，使用不含个人配置或记录的源码副本。在仓库根目录依次执行；任一步失败时先处理错误再继续：

```powershell
npm ci --prefix frontend
npm ci --prefix desktop
uv sync --project backend --frozen
npm --prefix frontend run build
npm run desktop:build
```

最后一步会构建控制面板、准备全量运行环境，再构建全量版。输出如下：

| 目录 | 内容 |
| --- | --- |
| `dist-installers/panel` | Panel Setup、Portable 和 `win-unpacked` |
| `dist-installers/full` | Full Setup、Portable 和 `win-unpacked` |
| `packaging/full-runtime` | 全量运行环境暂存目录和文件哈希清单 `manifest.json` |

完成依赖安装和前端构建后，也可用 `npm run desktop:build:control` 或 `npm run desktop:build:full` 单独构建一版。只准备全量运行环境时使用 `npm run desktop:stage:full`。

正式入口是 `desktop/main.cjs`、`desktop/preload.cjs`、`desktop/electron-builder.*.json` 和 `scripts/stage-full-runtime.py`。`scripts/build-windows.ps1`、旧 YAML 配置及 `packaging/electron` 为迁移参考，不参与当前构建。

## 测试与发布

本地源码检查可执行：

```powershell
uv run --project backend --frozen python -m pytest -q
python scripts/audit-release.py
python scripts/audit-release.py packaging/full-runtime/mirofish
```

全量暂存过程会排除 `.env`、上传记录、`studio_data`、`record_backups`、日志和数据库等本地数据。文件哈希清单用于检查暂存内容，不能替代密钥扫描。

GitHub Actions 的 `Build Windows installers` 工作流在推送 `v*` 标签时运行，也可手动指定已有标签。它签出该标签的源码，安装锁定依赖，执行源码测试和密钥扫描，构建两版安装包，并在临时 Windows 环境中实际安装、启动及卸载全量版。检查包括服务版本、首页、图标、内置 Python、数据目录和卸载保留数据。

工作流要求标签与桌面版本一致，生成四个 EXE 的 SHA-256，上传后核对 GitHub 返回的哈希，再发布 Release。手动运行关闭 `publish` 时只保存工作流构建产物。`SHA256SUMS.txt` 随对应 Release 安装包提供，不作为源码中的固定校验表；下载时应使用同一 Release 的文件核验。

安装检查不调用真实模型或 Zep 付费接口，不能代替完整推演验收。当前安装包未使用发布者证书签名，Windows 可能显示未知发布者提示。
