@echo off
REM ZoViD - Guvenlik Paneli Baslat
REM Dogru Python ortamiyla calistirir (pose_project venv)

echo ============================================
echo  ZoViD Guvenlik Paneli Baslatiliyor...
echo ============================================
echo.

set VENV_PYTHON=C:\Users\Rukiye\pose_project\venv\Scripts\python.exe

if not exist "%VENV_PYTHON%" (
    echo HATA: Venv Python bulunamadi: %VENV_PYTHON%
    echo Lutfen requirements.txt'i yukleyin.
    pause
    exit /b 1
)

echo Python: %VENV_PYTHON%
echo Adres:  http://localhost:5000
echo.
echo Durdurmak icin CTRL+C
echo ============================================
echo.

"%VENV_PYTHON%" run.py

pause
