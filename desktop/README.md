# MiroFish Studio 桌面端

MiroFish Studio 以 Electron 桌面窗口承载本地工作台，提供托盘、菜单和原生
窗口行为，不需要打开浏览器。工作台只在本机 `127.0.0.1:3888` 上运行，
数据和推演引擎由本地 Studio 管理。

## 两种 Windows 安装包

| 安装包 | 适用场景 | 目标电脑要求 |
| --- | --- | --- |
| `MiroFish-Studio-Panel-*.exe` | 只安装桌面控制面板 | 已有 Studio 兼容工作目录和后端依赖；首次启动可选择目录 |
| `MiroFish-Studio-Full-*.exe` | 从零安装桌面端、Studio、后端和 Python 依赖 | Windows x64；无需另装 Node.js、Python 或 uv |

Panel 所选目录必须包含 `local_studio/server.py`、`backend` 和可用的 Python
运行环境；只有上游源码、没有 Studio 层的目录不能直接使用。Panel 会尝试
启动该目录的本地服务。Full 包含独立运行环境。

控制面板版不会覆盖已有的推演记录、模型预设或 Zep 配置。全量版只携带
程序代码、构建后的界面和通用 Python 依赖，不携带开发机的 `.env`、API
Key、Cookie、`studio_data`、`record_backups` 或上传记录；首次运行时数据
目录位于 `%APPDATA%\mirofish-studio-desktop\data`，不会写回安装资源目录。

## 构建

构建电脑需要 Windows x64、Node.js 22、Python 3.11 x64 和 uv。在不含个人
配置或记录的源码副本中，从仓库根目录依次执行；任一步失败时先处理错误：

```powershell
npm ci --prefix frontend
npm ci --prefix desktop
uv sync --project backend --frozen
npm --prefix frontend run build
npm run desktop:build
```

该流程一次构建两版，并自动准备全量运行环境。每个版本都会生成 NSIS
安装程序、portable 便携版和 `win-unpacked` 本地验收目录，输出分别位于
`dist-installers/panel` 与 `dist-installers/full`。

依赖和前端准备好后，可用 `npm run desktop:build:control` 或
`npm run desktop:build:full` 单独构建一版；只准备全量运行环境时使用
`npm run desktop:stage:full`。`packaging/full-runtime/manifest.json` 记录
暂存文件的大小和哈希；发布前仍需执行密钥扫描。

GitHub Actions 会签出指定发布标签的源码，执行测试、扫描、构建以及全量版
安装启动和卸载检查，核对上传文件哈希后发布 Release。`SHA256SUMS.txt`
随对应 Release 提供，不作为源码中的固定校验表。完整命令与发布步骤见
[Windows 打包说明](../packaging/WINDOWS_PACKAGING.md)。

开发预览可运行 `npm run desktop:dev`。如果尚未安装桌面依赖，旧的
`MiroFish管理器.bat` 仍可作为故障排查入口，但日常使用应从桌面应用或安装
包创建的快捷方式启动。

## 图标和安全边界

`assets/mirofish-logo.svg` 是图标源文件，`icons` 脚本生成多尺寸 PNG、ICO
和托盘图标。安装器、桌面快捷方式、托盘和工作台 favicon 使用同一套深绿
底白色星光标记，不再使用系统默认的 IE 图标。

桌面壳只允许本机 Studio 地址导航，渲染进程没有 Node.js 权限，开发者工具
快捷键被关闭；退出时只会有序停止它自己启动的本地服务，不会结束用户另行
启动的 MiroFish 进程。

`main.cjs`、`preload.cjs` 与 `electron-builder.*.json` 是本目录的正式构建
入口。早期 `main.js`、YAML 配置、`scripts/build-windows.ps1` 和
`packaging/electron` 仍保留作迁移参考，不参与当前两版安装包构建。
