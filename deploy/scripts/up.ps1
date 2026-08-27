param(
    [switch]$WithHermes
)

$ErrorActionPreference = "Stop"

function New-RandomServiceKey {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToHexString($bytes).ToLowerInvariant()
}

function Set-EnvValue {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )

    $updated = New-Object System.Collections.Generic.List[string]
    $found = $false
    foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
        if ($line.StartsWith("${Name}=")) {
            if (-not $found) {
                $updated.Add("${Name}=${Value}")
                $found = $true
            }
            continue
        }
        $updated.Add($line)
    }
    if (-not $found) {
        $updated.Add("${Name}=${Value}")
    }
    [System.IO.File]::WriteAllLines(
        $Path,
        $updated,
        (New-Object System.Text.UTF8Encoding($false))
    )
}

function Initialize-ServiceKey {
    param([string]$Name)

    $matches = @(Select-String -Path .env -Pattern "^$([regex]::Escape($Name))=(.*)$")
    $value = if ($matches.Count) { $matches[-1].Matches[0].Groups[1].Value } else { $null }
    if (-not $value) {
        $value = New-RandomServiceKey
    }
    if ($matches.Count -ne 1 -or -not $matches[0].Matches[0].Groups[1].Value) {
        Set-EnvValue -Path (Resolve-Path .env) -Name $Name -Value $value
    }
}

function Refresh-HermesSandboxAttestation {
    & sh (Join-Path $DeployRoot "scripts\refresh-hermes-sandbox-attestation.sh")
    if ($LASTEXITCODE -ne 0) { throw "Hermes sandbox attestation admission failed with exit code $LASTEXITCODE" }
}

function Prepare-HermesSource {
    & sh (Join-Path $DeployRoot "scripts\prepare-hermes-source.sh")
    if ($LASTEXITCODE -ne 0) { throw "Hermes source preparation failed with exit code $LASTEXITCODE" }
}

$DeployRoot = Split-Path -Parent $PSScriptRoot
$ProjectRoot = Split-Path -Parent $DeployRoot

if (-not (Test-Path (Join-Path $ProjectRoot "backend\Dockerfile"))) {
    throw "backend/ is missing beside deploy/."
}
if (-not (Test-Path (Join-Path $ProjectRoot "web-platform\package.json"))) {
    throw "web-platform/ is missing beside deploy/."
}

Push-Location $DeployRoot
try {
    if (-not (Test-Path .env)) {
        Copy-Item .env.example .env
        Write-Warning "Created deploy/.env. Replace the placeholder passwords and JWT secret, then run this script again."
        exit 1
    }

    Initialize-ServiceKey -Name "RAG_QUERY_EMBEDDING_TOKEN"
    $settings = Get-Content .env -Raw | ConvertFrom-StringData
    $requiredSecrets = @("POSTGRES_PASSWORD", "JWT_SECRET_KEY", "ADMIN_PASSWORD")
    foreach ($name in $requiredSecrets) {
        $value = $settings[$name]
        if (-not $value -or $value -like "change-this*") {
            throw "Set a non-placeholder $name in deploy/.env before starting."
        }
    }
    $ragEnabled = if ($settings.RAG_EMBEDDING_ENABLED) { $settings.RAG_EMBEDDING_ENABLED.ToLowerInvariant() } else { "false" }
    $appEnv = if ($settings.APP_ENV) { $settings.APP_ENV.ToLowerInvariant() } else { "container" }
    if ($appEnv -in @("production", "prod", "staging") -and $ragEnabled -ne "true") {
        throw "RAG_EMBEDDING_ENABLED=true is required in staging/production."
    }
    $composeProfile = @()
    $appServices = @("api", "web")
    if ($ragEnabled -eq "true") {
        foreach ($name in @("RAG_EMBEDDING_API_URL", "RAG_EMBEDDING_API_KEY", "RAG_QUERY_EMBEDDING_TOKEN", "RAG_QUERY_AUDIT_HMAC_KEY")) {
            $value = $settings[$name]
            if (-not $value -or $value -like "change-this*" -or $value -like "replace-with*" -or $value -eq "development-only-change-me" -or $value -eq "admin123") {
                throw "Set a non-placeholder $name before enabling RAG embedding."
            }
        }
        $composeProfile = @("--profile", "rag")
        $appServices = @("rag-worker", "api", "web")
    }
    $composeFiles = @("-f", "compose.yaml")
    if ($WithHermes) {
        Initialize-ServiceKey -Name "HERMES_API_SERVER_KEY"
        $settings = Get-Content .env -Raw | ConvertFrom-StringData
        $composeFiles += @("-f", "compose.hermes.yaml")
    }

    if ($WithHermes) {
        Prepare-HermesSource
        docker compose --env-file .env @composeProfile @composeFiles up -d db hermes --build --wait --wait-timeout 180
        if ($LASTEXITCODE -ne 0) { throw "Hermes services failed with exit code $LASTEXITCODE" }
        Refresh-HermesSandboxAttestation
        docker compose --env-file .env @composeProfile @composeFiles up -d @appServices --build --wait --wait-timeout 180
    } else {
        docker compose --env-file .env @composeProfile @composeFiles up -d --build --wait --wait-timeout 180
    }
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed with exit code $LASTEXITCODE" }
    docker compose --env-file .env @composeFiles ps
    if ($LASTEXITCODE -ne 0) { throw "docker compose ps failed with exit code $LASTEXITCODE" }

    $bind = if ($settings.APP_BIND) { $settings.APP_BIND } else { "127.0.0.1" }
    $port = if ($settings.APP_PORT) { $settings.APP_PORT } else { "8080" }
    $browserHost = if ($bind -eq "0.0.0.0") { "localhost" } else { $bind }
    Write-Output "Hermes Platform: http://${browserHost}:${port}"
    Write-Output "Swagger UI:     http://${browserHost}:${port}/docs"
} finally {
    Pop-Location
}
