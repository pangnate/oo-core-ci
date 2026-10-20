$ErrorActionPreference = 'Stop'
New-Item dist -ItemType Directory -Force | Out-Null

$branding = Get-Content config\branding.json -Raw | ConvertFrom-Json
$versionParts = $branding.version.Split('.')
if ($versionParts.Length -ne 4) { throw 'branding.version must have four components' }
$productVersion = $versionParts[0..2] -join '.'
$buildNumber = $versionParts[3]
$zipName = "core10-windows-$productVersion-build-$buildNumber.zip"

$smoke = Get-Content vendor\work\x2t-baseline-smoke-receipt.json -Raw | ConvertFrom-Json
if ($smoke.status -ne 'passed') { throw 'Windows runtime smoke did not pass' }
$originalHash = (Get-FileHash core\build\bin\win_64\x2t.exe -Algorithm SHA256).Hash.ToLower()
if ($smoke.x2t.sha256 -ne $originalHash) { throw 'Smoke-tested X2T differs from the build handoff' }

$packageRoot = Join-Path $env:RUNNER_TEMP 'core10-windows-baseline'
New-Item $packageRoot -ItemType Directory -Force | Out-Null
Copy-Item core\build\bin\win_64\* $packageRoot -Recurse -Force
Copy-Item vendor\work\x2t-baseline-smoke\fonts $packageRoot\fonts -Recurse -Force
Copy-Item runtime\native-window-shim.js $packageRoot\native-window-shim.js -Force
Copy-Item runtime\README.md $packageRoot\NATIVE-SDKJS-README.md -Force
Copy-Item config\branding.json $packageRoot\branding.json -Force
Copy-Item scripts\configure_native_runtime.py $packageRoot\configure_native_runtime.py -Force
Copy-Item vendor\work\x2t-baseline-smoke-receipt.json dist\runtime-baseline-receipt.json -Force

python scripts\brand_windows_runtime.py --runtime-bin $packageRoot --receipt dist\windows-branding-receipt.json
if ($LASTEXITCODE) { exit $LASTEXITCODE }
$zipPath = Join-Path dist $zipName
Compress-Archive -Path (Join-Path $packageRoot '*') -DestinationPath $zipPath -CompressionLevel Optimal
Copy-Item (Join-Path $packageRoot 'x2t.exe') dist\x2t-windows-amd64.exe
$exeHash = (Get-FileHash dist\x2t-windows-amd64.exe -Algorithm SHA256).Hash.ToLower()
$zipHash = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLower()
"$exeHash  x2t-windows-amd64.exe" | Set-Content dist\SHA256SUMS-windows-amd64
"$zipHash  $zipName" | Add-Content dist\SHA256SUMS-windows-amd64
Get-ChildItem dist
