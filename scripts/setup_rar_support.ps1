param(
    [switch]$Install7Zip
)

$ErrorActionPreference = "Stop"

function Resolve-Python {
    if (Test-Path ".\.venv\Scripts\python.exe") {
        return (Resolve-Path ".\.venv\Scripts\python.exe").Path
    }
    $python = (Get-Command python -ErrorAction SilentlyContinue)
    if ($python) {
        return $python.Path
    }
    throw "Python no encontrado en .venv ni en PATH."
}

function Upsert-EnvVar {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )
    if (-not (Test-Path $Path)) {
        Set-Content -Path $Path -Value ""
    }
    $content = Get-Content $Path
    $pattern = "^${Name}="
    if ($content | Where-Object { $_ -match $pattern }) {
        $updated = $content | ForEach-Object {
            if ($_ -match $pattern) { "${Name}=${Value}" } else { $_ }
        }
        Set-Content -Path $Path -Value $updated
    } else {
        Add-Content -Path $Path -Value "${Name}=${Value}"
    }
}

$python = Resolve-Python
Write-Host "Python:" $python

& $python -m pip install rarfile | Out-Host

if ($Install7Zip) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "Intentando instalar 7-Zip via winget..."
        & $winget.Path install --id 7zip.7zip -e --silent --accept-package-agreements --accept-source-agreements | Out-Host
    } else {
        Write-Host "winget no disponible. No se pudo intentar la instalacion automatica de 7-Zip."
    }
}

$detector = @'
from src.core.config import reload_settings
from src.processing.rar_support import detect_rar_backend

settings = reload_settings()
info = detect_rar_backend(settings, refresh=True)
print("available=", info.available)
print("backend_type=", info.backend_type)
print("backend_path=", info.backend_path)
print("message=", info.message)
'@

$result = $detector | & $python -
$result | Out-Host

$available = ($result | Select-String "available=\s*True")
$backendTypeLine = ($result | Select-String "backend_type=" | Select-Object -First 1)
$backendPathLine = ($result | Select-String "backend_path=" | Select-Object -First 1)

if ($available) {
    $backendType = ($backendTypeLine -replace ".*backend_type=\s*", "").Trim()
    $backendPath = ($backendPathLine -replace ".*backend_path=\s*", "").Trim()
    $envPath = ".env"
    Upsert-EnvVar -Path $envPath -Name "RAR_BACKEND_TYPE" -Value $backendType
    Upsert-EnvVar -Path $envPath -Name "RAR_BACKEND_PATH" -Value $backendPath
    Upsert-EnvVar -Path $envPath -Name "ARCHIVE_INSPECTION_ENABLED" -Value "true"
    Write-Host "RAR support configurado en .env con backend" $backendType "->" $backendPath
} else {
    Write-Host "No se detecto backend RAR funcional."
    Write-Host "Opciones recomendadas en Windows:"
    Write-Host "1. Instalar 7-Zip: winget install --id 7zip.7zip -e --silent --accept-package-agreements --accept-source-agreements"
    Write-Host "2. O instalar WinRAR para obtener UnRAR.exe / rar.exe"
    Write-Host "3. Luego volver a ejecutar: .\scripts\setup_rar_support.ps1"
}
