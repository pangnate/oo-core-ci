param(
  [string]$Python = "python",
  [string]$QtVersion = "5.15.2",
  [string]$Arch = "win64_msvc2019_64"
)
$ErrorActionPreference='Stop'
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Tmp=Join-Path $Root '.download-tmp\qt-win'
$Out=Join-Path $Root 'vendor\archives\qt_5.15.2_msvc2019_64.7z'

function Find-7Zip {
  $cmd = Get-Command 7z.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $candidates = @(
    "$env:ProgramFiles\7-Zip\7z.exe",
    "${env:ProgramFiles(x86)}\7-Zip\7z.exe"
  )
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path $candidate)) { return $candidate }
  }
  return $null
}

$SevenZip = Find-7Zip
if (-not $SevenZip) {
  throw "7-Zip not found. Install 7-Zip or add 7z.exe to PATH."
}
Write-Host "Using 7-Zip: $SevenZip"

Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue
New-Item $Tmp -ItemType Directory -Force | Out-Null
& $Python -m pip install --disable-pip-version-check aqtinstall
& $Python -m aqt install-qt windows desktop $QtVersion $Arch -O $Tmp
$QtDir=Join-Path $Tmp "$QtVersion\msvc2019_64"
if (!(Test-Path (Join-Path $QtDir 'bin\qmake.exe'))) { throw "qmake.exe not found under $QtDir" }
New-Item (Split-Path $Out) -ItemType Directory -Force | Out-Null
Remove-Item $Out -Force -ErrorAction SilentlyContinue
Push-Location (Join-Path $Tmp $QtVersion)
try {
  & $SevenZip a -t7z -mx=7 $Out 'msvc2019_64' | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "7-Zip failed with exit code $LASTEXITCODE" }
} finally {
  Pop-Location
}
& $Python (Join-Path $Root 'scripts\update_checksum.py') $Out 'qt_windows_amd64'
Write-Host "Created $Out"
