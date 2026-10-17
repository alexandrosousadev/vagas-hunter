@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Coletando vagas e avaliando as melhores com o Ollama...
.\.venv\Scripts\python.exe run.py coletar

