param([string]$Python='python')
$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
$runtimeRoot=Join-Path $projectRoot 'runtime'
$downloadRoot=Join-Path $runtimeRoot 'downloads'
$unpackRoot=Join-Path $runtimeRoot 'unpacked'
$tempRoot=Join-Path $projectRoot '.cache/temp'
New-Item -ItemType Directory -Force -Path $runtimeRoot,$downloadRoot,$unpackRoot,$tempRoot | Out-Null
$env:TEMP=$tempRoot
$env:TMP=$tempRoot
$packages=@(
    @{Name='ngspice-47_64.7z';Url='https://downloads.sourceforge.net/project/ngspice/ng-spice-rework/47/ngspice-47_64.7z';Hash='59225971bd68cdd1199443649aa4615a9e6d684933f205ab49006a3942518f5a'},
    @{Name='ngspice-47_dll_64.7z';Url='https://downloads.sourceforge.net/project/ngspice/ng-spice-rework/47/ngspice-47_dll_64.7z';Hash='5bf5eec7db989f74849cdb32f7df62693f4f149cceeebcbd222eb35c2bb821eb'},
    @{Name='openvaf22.zip';Url='https://openva.fra1.cdn.digitaloceanspaces.com/openvaf_22_12_0_windows_amd64.zip';Hash='7307066cd93576ce2ee8fe4ea8f4156c505aabd1dd95e30e4df6fd7fee052856'}
)
foreach ($pkg in $packages) {
    $archive=Join-Path $downloadRoot $pkg.Name
    if (!(Test-Path -LiteralPath $archive)) { Invoke-WebRequest -Uri $pkg.Url -OutFile $archive }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower() -ne $pkg.Hash) { throw "Checksum mismatch: $($pkg.Name)" }
    if ($pkg.Name.EndsWith('.zip')) { Expand-Archive -LiteralPath $archive -DestinationPath $unpackRoot -Force }
    else {
        # Windows tar may report empty directory entries in 7z; required extracted files are checked below.
        & tar -xf $archive -C $unpackRoot
    }
}
$files=@('Spice64_dll/dll-vs/ngspice.dll','Spice64_dll/dll-vs/libomp140.x86_64.dll','Spice64/bin/sndfile.dll','Spice64/bin/samplerate.dll','Spice64/bin/ngspice_con.exe','openvaf.exe')
foreach($relative in $files) {
    $source=Join-Path $unpackRoot $relative
    if (!(Test-Path -LiteralPath $source)) {throw "Missing extracted file: $relative"}
    Copy-Item -LiteralPath $source -Destination $runtimeRoot -Force
}
$modelPath=Join-Path $projectRoot 'models/asmhemt.va'
$modelHash='189002cdd52996994cb4dcf7171050374237832f61dbfa1a3a43cc4439c94edc'
if (!(Test-Path -LiteralPath $modelPath)) {
    Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/rafapm/dfo_parameter_extraction/a8d945a1d2f70c27998be7d0071cd6602bca02b5/notebooks/HEMT_ex/ngspice_notebook_and_files/asmhemt.va' -OutFile $modelPath
}
if ((Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash.ToLower() -ne $modelHash) {throw 'ASM-HEMT source hash mismatch; preserve the changed source before continuing.'}
& (Join-Path $runtimeRoot 'openvaf.exe') (Join-Path $projectRoot 'models/asmhemt.va') -o (Join-Path $projectRoot 'models/asmhemt.osdi')
if ($LASTEXITCODE -ne 0) {throw 'OpenVAF compilation failed'}
& $Python -m pip install --no-cache-dir --target (Join-Path $projectRoot '.deps') -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) {throw 'Python dependency installation failed'}
Write-Host 'Local runtime and dependencies are ready.'
