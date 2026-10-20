@echo off
setlocal EnableExtensions
if "%REAL_VCVARSALL%"=="" exit /b 2
call "%REAL_VCVARSALL%" x64 -vcvars_ver=14.29
if errorlevel 1 exit /b 1
if /I "%~1"=="deps" goto prepare
if /I "%~1"=="prepare" goto prepare
if /I "%~1"=="core" goto core
if not "%~1"=="" exit /b 2
:prepare
python scripts\prepare.py --platform windows || exit /b 1
python scripts\patch_x2t_sln.py --core-root core || exit /b 1
python scripts\configure_build.py --platform windows --vs-path "%CD%\ci\vswrap" || exit /b 1
if /I "%~1"=="prepare" exit /b 0
python scripts\make_minimal_deps.py || exit /b 1
if /I "%~1"=="deps" exit /b 0
:core
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\generate_import_libs.ps1 -LibDir "%CD%\core\build\lib\win_64" || exit /b 1
python scripts\build_x2t.py || exit /b 1
if not exist core\build\bin\win_64\x2t.exe exit /b 1
copy /Y core\build\lib\win_64\*.dll core\build\bin\win_64\ >nul
copy /Y core\Common\3dParty\icu\win_64\build\*.dll core\build\bin\win_64\ >nul
if exist core\build\lib\win_64\system xcopy /E /I /Y core\build\lib\win_64\system core\build\bin\win_64\system >nul
exit /b 0
