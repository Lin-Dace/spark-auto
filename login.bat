@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 即将打开浏览器，请用抖音 App 扫码登录
python main.py login --platform douyin
pause
