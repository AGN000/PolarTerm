@echo off
REM Build PolarTerm.exe on Windows
REM Requirements: Python 3.10+ and pip
echo === PolarTerm Windows Build ===
python --version
pip --version

echo Installing dependencies...
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller pillow

echo Building exe with PyInstaller...
REM Use --onefile --windowed for single exe, or use spec
pyinstaller --noconfirm --clean --windowed --onefile --icon=resources/polarterm.ico --name=PolarTerm --add-data "resources/polarterm.png;resources" --add-data "resources/polarterm.ico;resources" main.py

if exist dist\PolarTerm.exe (
    echo Build SUCCESS: dist\PolarTerm.exe
    dir dist\PolarTerm.exe
    echo.
    echo To run: dist\PolarTerm.exe
    echo To create installer, install Inno Setup and run: iscc installer.iss
) else (
    echo Build FAILED - check output
    exit /b 1
)
pause
