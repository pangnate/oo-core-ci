param([string]$LibDir)
$ErrorActionPreference='Stop'
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (!(Test-Path $LibDir)) { throw "Missing $LibDir" }
$Pri=Join-Path $Root 'core\X2tConverter\build\Qt\X2tConverter.pri'
if (!(Test-Path $Pri)) { throw "Missing $Pri" }
$txt=Get-Content $Pri -Raw
$m=[regex]::Match($txt,'ADD_DEPENDENCY\(([^)]+)\)')
if(!$m.Success){ throw 'Could not parse ADD_DEPENDENCY(...) from X2tConverter.pri' }
$Required=$m.Groups[1].Value.Split(',') | ForEach-Object {$_.Trim()} | Where-Object {$_}
Write-Host "Dynamic import libraries required by this Core baseline: $($Required -join ', ')"
foreach($name in $Required){
  $lib=Join-Path $LibDir ($name+'.lib')
  if(Test-Path $lib){ Write-Host "[reuse] $lib"; continue }
  $dll=Get-ChildItem $LibDir -File | Where-Object { $_.Name -ieq ($name+'.dll') -or $_.Name -ieq ('lib'+$name+'.dll') } | Select-Object -First 1
  if(-not $dll){ throw "Required DLL not found for $name in $LibDir" }
  $raw=& dumpbin.exe /nologo /exports $dll.FullName
  $exports=New-Object System.Collections.Generic.List[string]
  foreach($line in $raw){
    if($line -match '^\s*\d+\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+(\S+)'){
      $sym=$Matches[1]
      if($sym -and -not $sym.StartsWith('[')){ $exports.Add($sym) }
    }
  }
  if($exports.Count -eq 0){ throw "No named exports parsed from $($dll.FullName). Supply the original $name.lib for this DLL." }
  $def=Join-Path $LibDir ($name+'.def')
  $defLines = @("LIBRARY `"$($dll.Name)`"", 'EXPORTS') + @($exports)
  $defLines | Set-Content -Encoding ASCII $def
  & lib.exe /nologo /def:$def /machine:x64 /out:$lib
  if($LASTEXITCODE -ne 0 -or !(Test-Path $lib)){ throw "lib.exe failed for $name" }
  Write-Host "[generated] $lib ($($exports.Count) named exports)"
}
