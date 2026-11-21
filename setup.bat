@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/4] 检查 Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo 没有找到 python，请先安装 Python 3.10+，安装时勾选 "Add Python to PATH"
  pause
  exit /b 1
)

echo [2/4] 安装依赖...
python -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo [3/4] 安装 Chromium（已安装会自动跳过）...
python -m playwright install chromium
if errorlevel 1 goto fail

echo [4/4] 检查好友配置...
if not exist friends.json (
  copy friends.example.json friends.json >nul
  echo 已生成 friends.json，请用记事本打开，把示例好友改成你自己的好友名字
) else (
  echo 已存在 friends.json，保留不动
)

echo.
echo 安装完成。下一步：双击 login.bat 扫码登录，然后双击 run.bat 测试发送
pause
exit /b 0

:fail
echo.
echo 安装失败，请检查网络后重新运行本脚本
pause
exit /b 1
