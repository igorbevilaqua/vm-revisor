@echo off
title Revisor de Roteiros - Viral Media Labs
cd /d "%~dp0"

echo ============================================
echo  Revisor de Roteiros - Viral Media Labs
echo ============================================
echo.

:: Carrega a API key do config.txt (se nao estiver no ambiente)
if not "%ANTHROPIC_API_KEY%"=="" goto :temchave

if not exist config.txt (
    echo ERRO: config.txt nao encontrado.
    echo Certifique-se de que o config.txt esta na mesma pasta.
    pause
    exit /b 1
)

for /f "tokens=2 delims==" %%a in ('findstr "ANTHROPIC_API_KEY" config.txt') do (
    set ANTHROPIC_API_KEY=%%a
)

if "%ANTHROPIC_API_KEY%"=="cole-sua-chave-aqui" (
    echo ERRO: Voce ainda nao configurou sua API key.
    echo Abra o config.txt e substitua "cole-sua-chave-aqui" pela sua chave.
    pause
    exit /b 1
)

if "%ANTHROPIC_API_KEY%"=="" (
    echo ERRO: API key nao encontrada no config.txt.
    pause
    exit /b 1
)

:temchave
echo Abrindo a interface no navegador...
echo (mantenha esta janela aberta durante a revisao)
echo.

python interface.py

echo.
pause
