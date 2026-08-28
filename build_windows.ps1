# Build PolarTerm.exe on Windows (PowerShell)
Write-Host "=== PolarTerm Windows Build (PowerShell) ===" -ForegroundColor Cyan
python --version
pip --version

Write-Host "Installing dependencies..." -ForegroundColor Yellow
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller pillow

Write-Host "Building exe..." -ForegroundColor Yellow
pyinstaller --noconfirm --clean --windowed --onefile --icon=resources/polarterm.ico --name=PolarTerm --add-data "resources/polarterm.png;resources" --add-data "resources/polarterm.ico;resources" main.py

if (Test-Path "dist/PolarTerm.exe") {
    Write-Host "Build SUCCESS: dist/PolarTerm.exe" -ForegroundColor Green
    Get-Item dist/PolarTerm.exe | Format-List
    Write-Host "To run: .\dist\PolarTerm.exe" -ForegroundColor Cyan
    Write-Host "To create installer: install Inno Setup, then: iscc installer.iss" -ForegroundColor Cyan
} else {
    Write-Host "Build FAILED" -ForegroundColor Red
    exit 1
}
