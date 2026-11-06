# Prepara bria-local en Windows: clona los repos si faltan y crea .env con claves nuevas.
#   powershell -ExecutionPolicy Bypass -File .\preparar.ps1
param([string]$Organizacion = "bria-app")

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

foreach ($repo in @("bria-web", "bria-api", "bria-engine")) {
    if (Test-Path -Path "repos/$repo") {
        Write-Host "repos/$repo ya existe"
    } else {
        git clone "https://github.com/$Organizacion/$repo.git" "repos/$repo"
        if ($LASTEXITCODE -ne 0) { throw "No se pudo clonar $repo. Revisa que puedas abrir el repositorio en GitHub." }
    }
}

if (Test-Path -Path ".env") {
    Write-Host ".env ya existe: no se cambia"
} else {
    function Nueva-Clave { return ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")) }
    function Nueva-Contrasena { return ("Qa-" + [guid]::NewGuid().ToString("N").Substring(0, 10) + "-26!") }

    $texto = [IO.File]::ReadAllText("$PSScriptRoot\.env.example")
    $valores = @{
        "POSTGRES_PASSWORD"    = Nueva-Clave
        "JWT_SECRET_KEY"       = Nueva-Clave
        "ENGINE_API_KEY"       = Nueva-Clave
        "DEMO_OWNER_PASSWORD"  = Nueva-Contrasena
        "DEMO_SELLER_PASSWORD" = Nueva-Contrasena
    }
    foreach ($nombre in $valores.Keys) {
        $texto = [regex]::Replace($texto, "(?m)^$nombre=\r?$", "$nombre=$($valores[$nombre])")
    }
    [IO.File]::WriteAllText("$PSScriptRoot\.env", $texto, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host ".env creado. Las claves de las cuentas de prueba: DEMO_OWNER_PASSWORD y DEMO_SELLER_PASSWORD."
}

Write-Host ""
Write-Host "Listo. Ahora ejecuta: docker compose up --build"
Write-Host "Y abre http://localhost:3000 cuando termine el servicio semilla."
