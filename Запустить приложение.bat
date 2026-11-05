@echo off
chcp 65001 > nul
rem Запуск приложения «Прогноз аренды квартиры». Откроется в браузере: http://localhost:8501
rem Чтобы остановить приложение, закройте это окно.
cd /d "%~dp0"
venv\Scripts\streamlit.exe run app.py
pause
