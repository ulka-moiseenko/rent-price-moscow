@echo off
chcp 65001 > nul
rem Полный запуск конвейера данных: резервная копия, сбор, загрузка, обучение. Около полутора часов.
rem Перед запуском программа просит подтверждение: без него ничего не изменится.
rem Журнал: logs\pipeline.log
cd /d "%~dp0"
venv\Scripts\python.exe src\pipeline.py
pause
