$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
 Write-Host "ERROR: instala Docker Desktop y habilita Docker Engine/WSL2 antes de continuar." -ForegroundColor Red
 exit 1
}
docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker Compose no está disponible" }
function New-Secret {
 $bytes = New-Object byte[] 24
 [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
 return ([BitConverter]::ToString($bytes)).Replace('-','').ToLowerInvariant()
}
$envFile = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $envFile)) {
 $vars = @{
  POSTGRES_ADMIN_PASSWORD = (New-Secret); DB_PRODUCTS_PASSWORD=(New-Secret); DB_CLIENTS_PASSWORD=(New-Secret)
  DB_LOANS_PASSWORD=(New-Secret); DB_INVENTORY_PASSWORD=(New-Secret)
  RABBIT_USER='credimarket'; RABBIT_PASSWORD=(New-Secret)
  JWT_SECRET=(New-Secret); INTERNAL_TOKEN=(New-Secret)
  DEMO_ADMIN_PASSWORD=(New-Secret); DEMO_CLIENT_PASSWORD=(New-Secret)
  DEMO_RISK_PASSWORD=(New-Secret); DEMO_SECOND_PASSWORD=(New-Secret)
 }
 $content = $vars.Keys | Sort-Object | ForEach-Object { "$_=$($vars[$_])" }
 [System.IO.File]::WriteAllLines($envFile,[string[]]$content)
 $access = @("CREDIMARKET - CREDENCIALES DE DEMOSTRACION (NO SUBIR A GIT)","URL: http://localhost:8080", "MLflow: http://localhost:5000", "RabbitMQ: http://localhost:15672", "RabbitMQ usuario: $($vars.RABBIT_USER)", "RabbitMQ clave: $($vars.RABBIT_PASSWORD)","", "Administrador: admin / $($vars.DEMO_ADMIN_PASSWORD)", "Cliente: cliente_demo / $($vars.DEMO_CLIENT_PASSWORD)","Riesgo alto: cliente_riesgo / $($vars.DEMO_RISK_PASSWORD)","Segundo cliente: cliente_dos / $($vars.DEMO_SECOND_PASSWORD)")
 [System.IO.File]::WriteAllLines((Join-Path $PSScriptRoot 'ACCESOS_LOCALES.txt'), [string[]]$access)
 Write-Host "Se generaron credenciales locales en ACCESOS_LOCALES.txt. NO publiques estos archivos." -ForegroundColor Green
}
Write-Host "Levantando CrediMarket en Docker Compose..." -ForegroundColor Cyan
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Write-Host "Error al iniciar. Revisa: docker compose logs --tail=150" -ForegroundColor Red;exit 1 }
docker compose ps
Write-Host "Abre http://localhost:8080 y usa las credenciales de ACCESOS_LOCALES.txt" -ForegroundColor Green
Start-Process "http://localhost:8080"
