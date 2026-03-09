@echo off
title FCBAgent — Build EXE
color 0A
echo.
echo  ================================================
echo   FCBPigeonsLive — Build FCBAgent.exe
echo  ================================================
echo.

REM Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERRO] Python nao encontrado!
    echo  Instale Python 3.10+ em python.org
    echo.
    pause
    exit /b 1
)

REM Instalar dependencias
echo  [1/3] Instalando dependencias...
pip install pyinstaller requests websocket-client pillow pystray --quiet

REM Build
echo  [2/3] Compilando FCBAgent.exe...
pyinstaller --onefile --windowed --icon=fcbagent.ico --name=FCBAgent fcbagent.py

REM Resultado
if exist dist\FCBAgent.exe (
    echo.
    echo  [3/3] SUCESSO!
    echo  Arquivo: dist\FCBAgent.exe
    echo.
    explorer dist
) else (
    echo.
    echo  [ERRO] Build falhou. Veja mensagens acima.
)

echo.
pause
