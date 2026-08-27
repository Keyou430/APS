$ErrorActionPreference = "Stop"
$DeployRoot = Split-Path -Parent $PSScriptRoot

Push-Location $DeployRoot
try {
    docker compose --env-file .env -f compose.yaml logs --follow --tail 200 @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose logs failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
