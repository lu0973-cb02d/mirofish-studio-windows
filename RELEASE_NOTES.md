# MiroFish Studio 1.1.0

这是 Windows 桌面工作台首个公开发布版本，基于 MiroFish 核心源码并增加本地 Studio 体验层。

## 发布内容

- `MiroFish-Studio-Panel-1.1.0-Setup.exe`：仅安装控制面板，选择已有的 MiroFish 工作目录。
- `MiroFish-Studio-Panel-1.1.0-Portable.exe`：控制面板便携版。
- `MiroFish-Studio-Full-1.1.0-Setup.exe`：包含 MiroFish 源码和 Python 运行环境的全量安装版，从零开始使用。
- `MiroFish-Studio-Full-1.1.0-Portable.exe`：全量便携版。

## 主要能力

- Clash 风格的本地桌面工作台，不依赖浏览器控制台。
- 多个模型预设：自定义 Base URL、Key、模型自动发现、一键切换。
- 多个 Zep 连接：限流/暂时故障时自动冷却和切换可用连接。
- 推演记录手动备份、定时自动备份、哈希校验、失败回滚和恢复前回退备份。
- 推演准备、双线轮次、报告和采访流程的状态持久化，短暂断线后刷新可继续查看。
- MiroFish 品牌图标和桌面快捷方式，不再使用浏览器默认图标。

## 使用提示

首次使用请在工作台中填写你自己的模型和 Zep 配置。API Key 使用当前 Windows 用户的 DPAPI 加密存储，发布的源码和安装包不包含个人密钥或过往推演记录。

安装包作为 GitHub Release 资产提供，源码按 AGPL-3.0 发布，详细边界见 `NOTICE.md`。

## 验证与限制

- 后端测试：171 项通过；本地/桌面逻辑测试：246 项通过。2 项符号链接测试因当前 Windows 用户没有创建符号链接权限而跳过。
- 前端生产构建、桌面端打包和本机启动健康检查通过；全量版启动使用安装包内置的 Python 运行时，并把用户数据写入 `%APPDATA%\mirofish-studio-desktop\data`。
- 本版本未使用真实模型或 Zep 密钥执行付费推演。首次使用需自行填写并测试连接。
- Windows 安装包未使用发布者证书签名，系统可能显示未知发布者提示。
