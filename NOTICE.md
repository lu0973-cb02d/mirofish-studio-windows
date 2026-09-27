# MiroFish Studio Windows 衍生版说明

本仓库以 MiroFish 上游代码为基础，加入 Windows 桌面工作台、模型/Zep 预设管理、推演记录备份恢复、断线续接保护和两套安装包构建流程。

## 许可证

仓库主体按根目录 `LICENSE` 中的 **GNU Affero General Public License v3.0 (AGPL-3.0)** 发布。上游代码、修改后的衍生代码以及与核心组合发布的部分必须继续遵守 AGPL-3.0。安装包中的第三方组件仍按各自许可证执行；请同时查看依赖项目的许可证和本地 `THIRD_PARTY_NOTICES` 文件（如有）。

AGPL-3.0 允许个人或商业使用、修改和收费分发，但分发修改版时必须提供对应源代码；如果通过网络向用户提供修改后的程序，还需要提供获取对应源代码的明确方式。完整条文见 <https://www.gnu.org/licenses/agpl-3.0.html>。

## 来源与版本

- 上游来源快照：`source_info.json` 中记录的 MiroFish 主分支提交。
- 本地体验层/Windows 桌面工作台版本：`1.1.0`。
- 项目维护者不得把上游版权、商标或第三方依赖的许可证声明移除或误标为 MIT。

## 隐私与发布边界

仓库不应包含 `.env`、API Key、Zep 密钥、个人推演记录、上传文件、运行日志、`studio_data`、`record_backups` 或构建时的虚拟环境。安装包只包含可分发的程序源码和运行依赖；用户首次使用时在本机配置自己的服务地址和密钥。
