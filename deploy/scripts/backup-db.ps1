$ErrorActionPreference = "Stop"
$DeployRoot = Split-Path -Parent $PSScriptRoot
$BackupRoot = Join-Path $DeployRoot "backups"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Destination = Join-Path $BackupRoot "agent-platform-${Timestamp}.dump"
$ContainerPath = "/tmp/agent-platform-backup.dump"

New-Item -ItemType Directory -Force $BackupRoot | Out-Null

Push-Location $DeployRoot
try {
    $settings = Get-Content .env -Raw | ConvertFrom-StringData
    $database = if ($settings.POSTGRES_DB) { $settings.POSTGRES_DB } else { "agent_platform" }
    $user = if ($settings.POSTGRES_USER) { $settings.POSTGRES_USER } else { "postgres" }
    # Custom format (-Fc): compressed, checksummed, restorable via pg_restore -l.
    # The dump is written inside the container and copied out with docker cp so
    # no PowerShell pipeline can corrupt the binary stream (PS5.1 BOM issue).
    docker compose --env-file .env -f compose.yaml exec -T db sh -c "pg_dump -U $user -d $database -Fc -f $ContainerPath"
    if ($LASTEXITCODE -ne 0) {
        throw "pg_dump failed with exit code $LASTEXITCODE"
    }
    $containerId = (docker compose --env-file .env -f compose.yaml ps -q db)
    if (-not $containerId) { throw "db container not found" }
    docker cp "${containerId}:${ContainerPath}" "$Destination"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Destination) -or (Get-Item $Destination).Length -eq 0) {
        throw "docker cp failed or produced an empty archive"
    }
    docker compose --env-file .env -f compose.yaml exec -T db rm -f $ContainerPath
    $hash = (Get-FileHash -Algorithm SHA256 -Path $Destination).Hash.ToLower()
    $size = (Get-Item $Destination).Length
    "$hash  $(Split-Path -Leaf $Destination)  $size bytes  db=$database" |
        Set-Content -Encoding ascii -Path "$Destination.sha256"
    Write-Output "Database backup: $Destination ($size bytes)"
    Write-Output "SHA256: $hash"
    Write-Output "Verify with: pg_restore -l $Destination"
} finally {
    Pop-Location
}
