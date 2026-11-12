<#
.SYNOPSIS
  Instala o actualiza los bots obreros de Colmena RPA como servicios de Windows Server (NSSM).

.EXAMPLE
  .\deploy\windows\install-service.ps1 -Version v2.0.0 -Instances 2

.NOTES
  Requiere: Python 3.12, Git y NSSM (https://nssm.cc) en el PATH. Ejecutar como administrador.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Version,
    [int] $Instances = 1,
    [string] $AppDir = "C:\colmena-rpa",
    [string] $EnvFile = "C:\colmena-rpa\worker.env",
    [string] $Repo = "https://github.com/DarwinMontiel/colmena-rpa.git"
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path "$AppDir\.git")) { git clone $Repo $AppDir }
git -C $AppDir fetch --tags --quiet
git -C $AppDir checkout --quiet $Version

python -m venv "$AppDir\.venv"
& "$AppDir\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$AppDir\.venv\Scripts\pip.exe" install --quiet $AppDir
$env:PLAYWRIGHT_BROWSERS_PATH = "$AppDir\ms-playwright"
& "$AppDir\.venv\Scripts\playwright.exe" install chromium

if (-not (Test-Path $EnvFile)) { Copy-Item "$AppDir\.env.example" $EnvFile }

# Variables del archivo .env -> entorno del servicio
$envVars = Get-Content $EnvFile | Where-Object { $_ -match '^\s*[A-Z_]+=' } |
    ForEach-Object { $_.Trim() }
$envVars += "PLAYWRIGHT_BROWSERS_PATH=$AppDir\ms-playwright"
New-Item -ItemType Directory -Force "$AppDir\logs" | Out-Null

for ($i = 1; $i -le $Instances; $i++) {
    $name = "colmena-obrera-$i"
    if (Get-Service $name -ErrorAction SilentlyContinue) {
        nssm stop $name | Out-Null
    } else {
        nssm install $name "$AppDir\.venv\Scripts\colmena-obrera.exe" | Out-Null
    }
    nssm set $name DisplayName "Colmena RPA - bot obrero $i" | Out-Null
    nssm set $name AppDirectory $AppDir | Out-Null
    nssm set $name AppEnvironmentExtra ($envVars + "RPA_WORKER_ID=$env:COMPUTERNAME-obrera-$i") | Out-Null
    nssm set $name Start SERVICE_AUTO_START | Out-Null
    nssm set $name AppStopMethodConsole 300000 | Out-Null   # Ctrl+C: termina la tarea en curso
    nssm set $name AppStdout "$AppDir\logs\$name.log" | Out-Null
    nssm set $name AppStderr "$AppDir\logs\$name.log" | Out-Null
    nssm set $name AppRotateFiles 1 | Out-Null
    nssm set $name AppRotateBytes 10485760 | Out-Null
    nssm start $name | Out-Null
    Write-Host "Servicio $name en ejecución ($Version)"
    Start-Sleep -Seconds 5   # reinicio escalonado
}
