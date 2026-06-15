# Script de Inicio Rápido para Claude Code con OpenRouter en Windows
# Guarda este script en tu directorio de trabajo y ejecútalo en PowerShell.

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "       INICIANDO CLAUDE CODE CON OPENROUTER" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

$keyFile = "C:\Users\Administrador\.claude\openrouter_key.txt"
$apiKey = ""

# 1. Intentar leer la clave guardada
if (Test-Path $keyFile) {
    $apiKey = Get-Content $keyFile -Raw
    $apiKey = $apiKey.Trim()
}

# 2. Si no hay clave guardada, solicitarla al usuario
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    Write-Host "No se encontró una clave de API de OpenRouter guardada." -ForegroundColor Yellow
    Write-Host "Puedes conseguir una clave gratis en: https://openrouter.ai/keys" -ForegroundColor Gray
    $apiKey = Read-Host "Introduce tu API Key de OpenRouter (comienza con sk-or-v1-...)"
    
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        Write-Host "[ERROR] Se requiere una API Key para continuar." -ForegroundColor Red
        Read-Host "Presiona Enter para salir..."
        exit
    }
    
    # Guardar la clave para futuras ejecuciones
    New-Item -ItemType File -Path $keyFile -Force | Out-Null
    Set-Content -Path $keyFile -Value $apiKey.Trim()
    Write-Host "[OK] API Key guardada en $keyFile para futuras sesiones." -ForegroundColor Green
} else {
    Write-Host "[OK] API Key cargada desde el almacenamiento local." -ForegroundColor Green
}

Write-Host ""

# 3. Modelos recomendados de OpenRouter
Write-Host "Modelos recomendados de OpenRouter:" -ForegroundColor Yellow
Write-Host "1) openrouter/free (Modelo gratuito por defecto)"
Write-Host "2) google/gemini-2.5-flash (Excelente balance velocidad/código)"
Write-Host "3) meta-llama/llama-3.1-8b-instruct:free (Gratuito y rápido)"
Write-Host "4) qwen/qwen-2.5-coder-32b-instruct (Especializado en código)"
Write-Host "5) Otro (Ingresar ruta de modelo personalizada)"
Write-Host ""

$option = Read-Host "Elige una opción [1-5]"
$model = "openrouter/free"

switch ($option) {
    "1" { $model = "openrouter/free" }
    "2" { $model = "google/gemini-2.5-flash" }
    "3" { $model = "meta-llama/llama-3.1-8b-instruct:free" }
    "4" { $model = "qwen/qwen-2.5-coder-32b-instruct" }
    "5" { 
        $customModel = Read-Host "Introduce la ruta del modelo (ejemplo: deepseek/deepseek-chat)"
        if (-not [string]::IsNullOrWhiteSpace($customModel)) {
            $model = $customModel
        }
    }
    default { $model = "openrouter/free" }
}

# 4. Configurar variables de entorno requeridas por Claude Code para OpenRouter
Write-Host ""
Write-Host "Configurando variables de entorno para la redirección a OpenRouter..." -ForegroundColor Cyan

# MUY IMPORTANTE:
# ANTHROPIC_BASE_URL debe apuntar a la raíz de la API de OpenRouter. 
# Claude Code añade internamente "/v1/messages" al final, resolviendo a la URL correcta de OpenRouter.
$env:ANTHROPIC_BASE_URL = "https://openrouter.ai/api"
$env:ANTHROPIC_AUTH_TOKEN = $apiKey
$env:ANTHROPIC_API_KEY = "" # Debe estar vacío para evitar conflictos de autenticación con Anthropic
$env:CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS = "true" # Desactiva funciones propietarias que OpenRouter no soporta (evita respuestas vacías)

# 5. Ejecutar Claude Code
Write-Host "Iniciando Claude Code con el modelo: $model" -ForegroundColor Green
Write-Host "Nota: Si ves advertencias de conflicto de login, son normales al usar proveedores externos." -ForegroundColor Gray
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

claude --model $model
