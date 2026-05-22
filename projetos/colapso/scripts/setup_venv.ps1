# Recria ou completa o venv do projeto colapso (Windows + Python 3.14).
# Uso: .\scripts\setup_venv.ps1
# Requer: venv já criado com  python -m venv venv

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root "venv\Scripts\python.exe"
$Pip = Join-Path $Root "venv\Scripts\pip.exe"

if (-not (Test-Path $Python)) {
    Write-Host "venv nao encontrado. Crie primeiro:" -ForegroundColor Yellow
    Write-Host "  python -m venv venv"
    exit 1
}

Write-Host "Python:" -NoNewline
& $Python --version

& $Python -m pip install -U pip setuptools wheel

function Install-ScipyWithRetry {
    param([int]$MaxAttempts = 3)
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        Write-Host "Instalando scipy (tentativa $i/$MaxAttempts)..." -ForegroundColor Cyan
        & $Pip install --no-cache-dir "scipy>=1.17.0"
        if ($LASTEXITCODE -eq 0) { return $true }
        Start-Sleep -Seconds 3
    }
    return $false
}

# scipy (~37 MB) costuma falhar por SSL intermitente; instalar antes do restante
if (-not (Install-ScipyWithRetry)) {
    Write-Host "Falha ao baixar scipy. Tente:" -ForegroundColor Red
    Write-Host "  - Outra rede / desativar inspecao HTTPS temporariamente"
    Write-Host "  - pip install --no-cache-dir scipy  (manual)"
    exit 1
}

& $Pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nVerificando pacotes..." -ForegroundColor Cyan
& $Pip check
& $Python -c @"
import MetaTrader5 as mt5
import numpy
print('OK: MetaTrader5', mt5.__version__, '| numpy', numpy.__version__)
try:
    import scipy
    print('OK: scipy', scipy.__version__)
except ImportError:
    print('AVISO: scipy nao instalado (opcional para hft_bot)')
"@

Write-Host "`nTestes do bot (opcional):" -ForegroundColor Cyan
Write-Host "  cd hft_bot"
Write-Host "  ..\venv\Scripts\python.exe tests\test_speed_filter.py"

Write-Host "`nSetup concluido." -ForegroundColor Green
