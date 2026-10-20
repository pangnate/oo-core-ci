$ErrorActionPreference = 'Stop'
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (!(Test-Path -LiteralPath $vswhere)) { throw 'Visual Studio Installer is missing' }
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (!$vs) { throw 'Visual Studio not found' }
$vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvarsall.bat'
$v142 = Get-ChildItem (Join-Path $vs 'VC\Tools\MSVC') -Directory |
  Where-Object { $_.Name -like '14.29*' } |
  Sort-Object Name -Descending |
  Select-Object -First 1
if (!$v142) { throw 'MSVC v142 (14.29) not installed on windows-2022 runner' }
"REAL_VCVARSALL=$vcvars" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
"X2T_COMPILER_VERSION=msvc-$($v142.Name)" | Out-File $env:GITHUB_ENV -Append -Encoding utf8
