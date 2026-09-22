@echo off
if "%REAL_VCVARSALL%"=="" (
  echo REAL_VCVARSALL is not set 1>&2
  exit /b 2
)
call "%REAL_VCVARSALL%" %* -vcvars_ver=14.29
exit /b %ERRORLEVEL%
