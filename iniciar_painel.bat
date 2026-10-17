@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Iniciando o painel do Vagas Hunter em http://localhost:8000 ...
.\.venv\Scripts\python.exe run.py painel
pause

