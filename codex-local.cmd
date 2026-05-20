@echo off
setlocal
chcp 65001 > nul
set "ROOT=%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%ROOT%src"
python -m codex_local %*
