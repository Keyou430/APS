$ErrorActionPreference = "Stop"
$Script = Join-Path $PSScriptRoot "local_ai_runtime.py"
& py -3.12 $Script status
exit $LASTEXITCODE
