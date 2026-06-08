@echo off
echo ============================================
echo  Instalando o Revisor de Roteiros...
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado.
    echo.
    echo Instale o Python em: https://www.python.org/downloads/
    echo IMPORTANTE: marque a opcao "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)

echo Instalando dependencias...
pip install -r requirements.txt

echo.
echo ============================================
echo  Instalacao concluida!
echo  Agora edite o config.txt e cole sua API key.
echo  Depois clique duas vezes em revisar.bat
echo ============================================
echo.
pause
