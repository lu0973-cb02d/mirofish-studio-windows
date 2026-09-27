# MiroFish Studio 桌面端

MiroFish Studio 现在以 Electron 桌面窗口承载本地工作台。用户看到的是
带托盘、菜单和原生窗口行为的功能型软件，不需要打开浏览器；页面仍只在
本机 `127.0.0.1:3888` 上工作，数据和推演引擎继续由本地 Studio 管理。

## 两种 Windows 安装包

| 安装包 | 适用场景 | 目标电脑要求 |
| --- | --- | --- |
| `MiroFish-Studio-Panel-*.exe` | 只安装桌面控制面板 | 已有 MiroFish 工作目录和后端依赖；首次启动可选择目录 |
| `MiroFish-Studio-Full-*.exe` | 从零安装桌面端、Studio、后端和 Python 依赖 | Windows x64；不需要另装 Python |

控制面板版不会覆盖已有的推演记录、模型预设或 Zep 配置。全量版只携带
程序代码、构建后的界面和通用 Python 依赖，不携带开发机的 `.env`、API
Key、Cookie、`studio_data`、`record_backups` 或上传记录；首次运行时数据
目录位于 `%APPDATA%\mirofish-studio-desktop\data`，不会写回安装资源目录。

## 构建

在仓库根目录执行：

```powershell
npm run desktop:install
npm run desktop:build:control
python scripts/stage-full-runtime.py
npm run desktop:build:full
```

也可以执行 `npm run desktop:build` 一次构建两版。每个版本都会生成 NSIS
安装程序、portable 便携版和 `win-unpacked` 本地验收目录，输出分别位于
`dist-installers/panel` 与 `dist-installers/full`。

全量 staging 会复制当前虚拟环境依赖，通常约 0.9 GB，打包时间取决于磁盘
速度。`packaging/full-runtime/manifest.json` 记录了每个文件的大小和哈希，
并明确标记没有用户数据和密钥。

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
入口。早期 `main.js`、YAML 配置和 `packaging/electron` 仍保留作迁移参考，
不参与当前两版安装包构建。
