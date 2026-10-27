param(
    [ValidateSet('report','verify','bootstrap','reproduce')][string]$Action='report',
    [string]$Python='python'
)
$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
if ($Action -eq 'bootstrap') {
    & (Join-Path $projectRoot 'bootstrap.ps1') -Python $Python
    exit
}
if ($Action -eq 'reproduce') {
    # Each replay gets a fresh results directory; the delivered frozen run is preserved.
    $replayRoot=Join-Path $projectRoot ('runs/'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
    New-Item -ItemType Directory -Path $replayRoot | Out-Null
    foreach ($folder in @('src','data','models','runtime')) {
        Copy-Item -LiteralPath (Join-Path $projectRoot $folder) -Destination $replayRoot -Recurse
    }
    $workspaceRoot=Split-Path (Split-Path $projectRoot -Parent) -Parent
    $dependencyRoot=Join-Path $projectRoot '.deps'
    if (!(Test-Path -LiteralPath $dependencyRoot)) {$dependencyRoot=Join-Path $workspaceRoot 'work/dfo_deps'}
    $env:PYTHONPATH=$dependencyRoot+[IO.Path]::PathSeparator+$env:PYTHONPATH
    $projectRoot=$replayRoot
    foreach ($step in @('fit','evaluate')) {
        & $Python (Join-Path $projectRoot 'src/baseline.py') $step
        if ($LASTEXITCODE -ne 0) { throw "Failed: $step" }
    }
    & $Python (Join-Path $projectRoot 'src/verify.py')
    if ($LASTEXITCODE -ne 0) { throw 'Verification failed' }
    Write-Host "Replayed run: $replayRoot"
}
if ($Action -eq 'verify') {
    & $Python (Join-Path $projectRoot 'src/verify.py')
} else {
    & $Python (Join-Path $projectRoot 'src/report.py')
}
if ($LASTEXITCODE -ne 0) { throw "Failed: $Action" }
