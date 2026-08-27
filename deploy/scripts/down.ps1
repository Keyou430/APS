$ErrorActionPreference = "Stop"
$DeployRoot = Split-Path -Parent $PSScriptRoot

Push-Location $DeployRoot
try {
    docker compose --env-file .env -f compose.yaml down
    if ($LASTEXITCODE -ne 0) { throw "docker compose down failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
