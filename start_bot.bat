@echo off
title BYBIT PAPER BOT
color 0A

echo ==========================================
echo         BYBIT PAPER TRADING BOT
echo ==========================================
echo.

cd /d %~dp0

echo Активируем venv...
call venv\Scripts\activate

echo.
echo Запуск бота...
echo.

python bybot.py

echo.
echo ==========================================
echo Бот остановлен
echo ==========================================
pause