# Script de Inicio Rápido para Claude Code con Ollama en Windows
# Guarda este script en tu directorio de trabajo y ejecútalo en PowerShell.

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "       INICIANDO CLAUDE CODE CON OLLAMA (LOCAL)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# Verificar si el servicio de Ollama está respondiendo
try {
    $response = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -ErrorAction Stop
    Write-Host "[OK] Servicio de Ollama detectado y ejecutándose." -ForegroundColor Green
} catch {
    Write-Host "[ERROR] El servicio de Ollama no está respondiendo en http://localhost:11434." -ForegroundColor Red
    Write-Host "Asegúrate de abrir la aplicación de Ollama primero." -ForegroundColor Yellow
    Read-Host "Presiona Enter para salir..."
    exit
}

# Preguntar qué modelo utilizar
Write-Host "Modelos locales disponibles en tu sistema:" -ForegroundColor Yellow
$response.models | ForEach-Object { Write-Host " - $($_.name)" }
Write-Host ""

# Detectar el mejor modelo disponible para proponer por defecto (priorizando gemma4)
$defaultModel = "qwen3.5:0.8b"
$hasGemma4 = $response.models | Where-Object { $_.name -like "*gemma4*" }
if ($hasGemma4) {
    $defaultModel = ($hasGemma4 | Select-Object -First 1).name
} else {
    $hasQwen = $response.models | Where-Object { $_.name -like "*qwen*" }
    if ($hasQwen) {
        $defaultModel = ($hasQwen | Select-Object -First 1).name
    }
}

$model = Read-Host "Introduce el nombre del modelo a usar [Por defecto: $defaultModel]"
if ([string]::IsNullOrWhiteSpace($model)) {
    $model = $defaultModel
}

Write-Host ""
Write-Host "Elige el método de inicio:" -ForegroundColor Yellow
Write-Host "1) Usar 'ollama launch claude' (Método recomendado, configura el entorno automáticamente)"
Write-Host "2) Configurar variables de entorno y ejecutar 'claude' directamente (Método tradicional)"
$method = Read-Host "Selecciona una opción [1 o 2]"

if ($method -eq "2") {
    Write-Host "Configurando variables de entorno de la sesión..." -ForegroundColor Cyan
    $env:ANTHROPIC_BASE_URL="http://localhost:11434"
    $env:ANTHROPIC_AUTH_TOKEN="ollama"
    $env:ANTHROPIC_API_KEY="ollama"
    
    Write-Host "Iniciando: claude --model $model" -ForegroundColor Green
    claude --model $model
} else {
    Write-Host "Iniciando: ollama launch claude --model $model" -ForegroundColor Green
    ollama launch claude --model $model
}
