@echo off
echo ============================================
echo  Instalando o Revisor de Roteiros...
echo ============================================
echo.

:: Detecta o comando Python disponivel (py > python > python3)
set PYCMD=
where py >nul 2>&1 && set PYCMD=py
if not defined PYCMD (where python >nul 2>&1 && set PYCMD=python)
if not defined PYCMD (where python3 >nul 2>&1 && set PYCMD=python3)
if not defined PYCMD (
    echo ERRO: Python nao encontrado.
    echo.
    echo Instale o Python em: https://www.python.org/downloads/
    echo IMPORTANTE: marque a opcao "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)

echo Instalando dependencias...
%PYCMD% -m pip install -r requirements.txt

echo.
echo ============================================
echo  Instalacao concluida!
echo  Agora edite o config.txt e cole sua API key.
echo  Depois clique duas vezes em revisar.bat
echo ============================================
echo.
pause
