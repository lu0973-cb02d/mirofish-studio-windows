# 完整版安装器的边界

完整安装包会把 MiroFish 的源码和安装脚本放到应用资源目录，并由
`bootstrap.ps1` 在目标电脑上创建独立的 `backend/.venv`。安装脚本只会从
Python 官方环境和 `requirements.txt` 安装依赖，不会复制开发机的 `.venv`、
`studio_data`、API Key 或推演记录。

首次启动前请在安装目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\full\bootstrap.ps1
```

网络受限时，依赖下载可能失败；安装器会保留已创建的虚拟环境，重新运行
脚本即可继续。控制面板本身仍然只访问 `127.0.0.1:3888`。
