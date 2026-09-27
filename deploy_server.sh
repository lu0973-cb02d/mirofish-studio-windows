#!/bin/bash
# MiroFish 云服务器一键部署脚本（Ubuntu）
# 用法：以 root 或有 sudo 权限的用户运行：bash deploy_server.sh
set -e

echo "==== [1/5] 安装基础工具 ===="
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -y
sudo apt-get install -y git curl

echo "==== [2/5] 安装 Docker（已装则跳过） ===="
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo systemctl enable --now docker

echo "==== [3/5] 下载 MiroFish 源码 ===="
cd ~
if [ ! -d MiroFish ]; then
  git clone --depth 1 https://github.com/666ghj/MiroFish.git
fi
cd MiroFish

echo "==== [4/5] 配置 API Key ===="
read -p "请输入你的 Gemini API Key（AIza 开头）: " GKEY
read -p "请输入 Zep API Key: " ZKEY
cat > .env <<EOF
# LLM API 配置：Google Gemini（OpenAI 兼容接口）
LLM_API_KEY=${GKEY}
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL_NAME=gemini-3.5-flash

# Zep 记忆服务
ZEP_API_KEY=${ZKEY}
EOF
echo ".env 已生成"

echo "==== [5/5] 启动 MiroFish ===="
sudo docker compose up -d

echo ""
echo "============================================"
echo "  部署完成！"
echo "  浏览器访问: http://$(curl -s ifconfig.me):3000"
echo "  查看日志:   sudo docker compose logs -f"
echo "  停止服务:   cd ~/MiroFish && sudo docker compose down"
echo "  重启服务:   cd ~/MiroFish && sudo docker compose restart"
echo "============================================"
