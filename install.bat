@echo off
chcp 65001 >nul 2>nul
setlocal EnableExtensions
title epubcc 安装

rem ---------------------------------------------------------------------------
rem epubcc 一键安装脚本（Windows）
rem
rem 用法：先安装好 Python（需要 3.9 或更高），然后在仓库目录双击或执行：
rem     install.bat
rem
rem 可选环境变量：
rem     EPUBCC_EXTRAS=detect,completion   同时安装可选依赖
rem     EPUBCC_VENV=路径                  自定义隔离环境目录
rem     EPUBCC_BIN=路径                   自定义命令安装目录
rem     EPUBCC_NO_PAUSE=1                 结束时不暂停
rem
rem 脚本会：检查 Python → 建隔离 venv → pip 装本仓库 → 生成 epubcc.cmd
rem 并加入用户 PATH。没有 Python 时直接拒绝执行。
rem ---------------------------------------------------------------------------

set "SRC_DIR=%~dp0"
if "%SRC_DIR:~-1%"=="\" set "SRC_DIR=%SRC_DIR:~0,-1%"
if not exist "%SRC_DIR%\epubcc.py" (
  echo [错误] 在 "%SRC_DIR%" 找不到 epubcc.py。
  echo        请把本脚本放在 epubcc 仓库目录里再运行。
  goto :fail
)

rem ---- 1. 检查 Python -----------------------------------------------------
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo [错误] 未检测到 Python，已拒绝安装。
  echo        请先安装 Python 3.9 或更高版本：https://www.python.org/downloads/
  echo        安装时请勾选 "Add python.exe to PATH"。
  goto :fail
)

%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [错误] 检测到的 Python 版本低于 3.9，请升级后重试。
  goto :fail
)
for /f "delims=" %%v in ('%PY% --version 2^>^&1') do echo [信息] 使用 %%v

rem ---- 2. 建隔离虚拟环境 -------------------------------------------------
if not defined EPUBCC_VENV set "EPUBCC_VENV=%LOCALAPPDATA%\epubcc\venv"
echo [信息] 创建隔离环境：%EPUBCC_VENV%
%PY% -m venv "%EPUBCC_VENV%"
if errorlevel 1 (
  echo [错误] 创建虚拟环境失败。
  goto :fail
)

set "SPEC=%SRC_DIR%"
if defined EPUBCC_EXTRAS set "SPEC=%SRC_DIR%[%EPUBCC_EXTRAS%]"

echo [信息] 安装 epubcc（含依赖 OpenCC，首次需要联网）...
"%EPUBCC_VENV%\Scripts\python.exe" -m pip install --quiet --upgrade pip
"%EPUBCC_VENV%\Scripts\python.exe" -m pip install --quiet --upgrade "%SPEC%"
if errorlevel 1 (
  echo [错误] 安装失败，请检查网络后重试。
  goto :fail
)

rem ---- 3. 生成命令并加入 PATH --------------------------------------------
if not defined EPUBCC_BIN set "EPUBCC_BIN=%LOCALAPPDATA%\epubcc\bin"
if not exist "%EPUBCC_BIN%" mkdir "%EPUBCC_BIN%"
> "%EPUBCC_BIN%\epubcc.cmd" echo @echo off
>> "%EPUBCC_BIN%\epubcc.cmd" echo "%EPUBCC_VENV%\Scripts\epubcc.exe" %%*

where powershell >nul 2>nul
if errorlevel 1 (
  echo [警告] 未找到 PowerShell，请手动把下面目录加入 PATH：
  echo        %EPUBCC_BIN%
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$d='%EPUBCC_BIN%'; $p=[Environment]::GetEnvironmentVariable('Path','User'); if($null -eq $p){$p=''}; if(($p -split ';') -notcontains $d){[Environment]::SetEnvironmentVariable('Path', ($p.TrimEnd(';') + ';' + $d), 'User'); Write-Host '  [信息] 已加入用户 PATH'} else {Write-Host '  [信息] 用户 PATH 中已存在'}"
)

set "PATH=%PATH%;%EPUBCC_BIN%"
echo [完成] 安装成功：
"%EPUBCC_BIN%\epubcc.cmd" --version
if errorlevel 1 (
  echo [错误] 安装后自检失败。
  goto :fail
)
echo.
echo 新开一个命令行窗口后即可使用，例如：  epubcc -t 一本书.epub
if not defined EPUBCC_NO_PAUSE pause
exit /b 0

:fail
echo.
if not defined EPUBCC_NO_PAUSE pause
exit /b 1
