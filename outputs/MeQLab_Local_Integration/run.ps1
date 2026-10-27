param(
    [ValidateSet('discover','acceptance')][string]$Mode='discover',
    [string]$Python='python',
    [string]$Config=(Join-Path $PSScriptRoot 'config.local.json')
)
$ErrorActionPreference='Stop'
if (!(Test-Path -LiteralPath $Config)) {throw 'Copy config.example.json to config.local.json and fill local paths first.'}
$env:PYTHONIOENCODING='utf-8'
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$result=Join-Path $PSScriptRoot ('results/'+$Mode+'_'+$stamp)
if ($Mode -eq 'discover') {
    & $Python (Join-Path $PSScriptRoot 'pmms_client.py') --config $Config --run-dir $result
} else {
    & $Python (Join-Path $PSScriptRoot 'connection_acceptance.py') --config $Config --results $result
}
exit $LASTEXITCODE
