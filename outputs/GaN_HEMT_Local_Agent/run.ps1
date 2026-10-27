param(
    [ValidateSet('run','resume','status','bootstrap','acceptance','fresh')][string]$Action='status',
    [string]$Python='python'
)
$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
function Invoke-CheckedPython {
    param([string[]]$Arguments)
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {throw ('Python step failed: '+($Arguments -join ' '))}
}
if ($Action -eq 'bootstrap') {& (Join-Path $projectRoot 'bootstrap.ps1') -Python $Python; exit}
if ($Action -eq 'fresh') {
    $freshRoot=Join-Path $projectRoot ('runs/'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
    New-Item -ItemType Directory -Path $freshRoot -Force | Out-Null
    foreach($folder in @('src','data','runtime','reference','tests')) {
        Copy-Item -LiteralPath (Join-Path $projectRoot $folder) -Destination $freshRoot -Recurse
    }
    New-Item -ItemType Directory -Path (Join-Path $freshRoot 'models') | Out-Null
    foreach($name in @('asmhemt.va','asmhemt.osdi')) {Copy-Item -LiteralPath (Join-Path $projectRoot ('models/'+$name)) -Destination (Join-Path $freshRoot 'models')}
    foreach($name in @('agent.py','protocol.json','requirements.txt','bootstrap.ps1','README.md','integration_requirements.md','THIRD_PARTY_LICENSE.txt','provenance.json','run.ps1')) {
        Copy-Item -LiteralPath (Join-Path $projectRoot $name) -Destination $freshRoot
    }
    $dependencyRoot=Join-Path $projectRoot '.deps'
    if (!(Test-Path -LiteralPath $dependencyRoot)) {$dependencyRoot=Join-Path (Split-Path (Split-Path $projectRoot -Parent) -Parent) 'work/dfo_deps'}
    $env:PYTHONPATH=$dependencyRoot+[IO.Path]::PathSeparator+$env:PYTHONPATH
    $projectRoot=$freshRoot
    $Action='run'
}
if ($Action -eq 'status') {
    $statePath=Join-Path $projectRoot 'results/run_state.json'
    if (!(Test-Path -LiteralPath $statePath)) {Write-Host 'Not run';exit}
    $state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    Write-Host ('Status: '+$state.status)
    Write-Host ('Completed: '+(($state.completed.PSObject.Properties.Name) -join ', '))
    exit
}
if ($Action -eq 'run') {
    Invoke-CheckedPython -Arguments @('-u',(Join-Path $projectRoot 'agent.py'),'run','--stop-after','curve_validate')
}
if ($Action -in @('run','resume')) {
    if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'results/acceptance_backend/backend_acceptance.json'))) {
        Invoke-CheckedPython -Arguments @('-u',(Join-Path $projectRoot 'tests/acceptance.py'),'backend')
    }
    Invoke-CheckedPython -Arguments @('-u',(Join-Path $projectRoot 'agent.py'),'run','--resume')
}
Invoke-CheckedPython -Arguments @((Join-Path $projectRoot 'tests/acceptance.py'),'final')
Write-Host ('Review: '+(Join-Path $projectRoot 'results/report/overview.html'))
