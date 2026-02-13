#!/bin/bash

# 项目初始化脚本
# 用于设置和运行贪吃蛇游戏开发环境

echo "🚀 正在初始化贪吃蛇游戏项目..."

# 检查是否安装了Python（用于启动简单的HTTP服务器）
if command -v python3 &> /dev/null; then
    echo "✅ Python3 已安装"
    SERVER_CMD="python3 -m http.server"
elif command -v python &> /dev/null; then
    echo "✅ Python 已安装"
    SERVER_CMD="python -m SimpleHTTPServer"
else
    echo "⚠️  未检测到Python，需要手动启动HTTP服务器"
    echo "请使用您喜欢的HTTP服务器打开index.html文件"
    echo "例如: 在项目目录下运行 'python -m http.server 8000'"
    exit 1
fi

echo "📁 项目结构:"
find . -type f -not -path "./.git/*" | sort

echo ""
echo "🎮 启动开发服务器..."
echo "请在浏览器中打开以下地址访问游戏:"
echo "http://localhost:8000/src/index.html"

# 在后台启动服务器
$SERVER_CMD 8000 &
SERVER_PID=$!

echo "🌐 服务器已启动 (PID: $SERVER_PID)"
echo "💡 按 Ctrl+C 停止服务器"

# 等待用户中断
trap "kill $SERVER_PID" INT
wait $SERVER_PID

echo "👋 服务器已停止"