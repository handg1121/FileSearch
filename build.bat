@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 exit /b 1
set "BUILD_EXIT_CODE=1"
set "BUILD_PYTHON=%CD%\.venv\Scripts\python.exe"
set "BUILD_RELEASE="
set "BUILD_NO_PAUSE="
set "PYTHONUTF8=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
:arguments
if "%~1"=="" goto arguments_done
if /I "%~1"=="--release" (set "BUILD_RELEASE=--release") else if /I "%~1"=="--no-pause" (set "BUILD_NO_PAUSE=1") else (
    echo ERROR: Unknown argument %~1
    goto finish
)
shift
goto arguments
:arguments_done
rem Only these scratch outputs are replaced by PyInstaller. Installed copies are separate.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "$scratchRoots = @((Join-Path (Get-Location) 'dist\_app\'), (Join-Path (Get-Location) 'dist\_launcher\')); foreach ($process in Get-Process -Name FileSearch,FileSearchApp -ErrorAction SilentlyContinue) { foreach ($scratchRoot in $scratchRoots) { if ($process.Path -and $process.Path.StartsWith($scratchRoot,[StringComparison]::OrdinalIgnoreCase)) { exit 1 } } }"
if errorlevel 1 (
    echo ERROR: Close the scratch app under dist\_app or dist\_launcher before building.
    goto finish
)
if exist "%BUILD_PYTHON%" goto check_python
if exist ".build-python\python.exe" goto local_python
where py >nul 2>nul
if errorlevel 1 goto missing_python
py -3.13 -m venv ".venv"
if errorlevel 1 goto failed
goto check_python
:local_python
".build-python\python.exe" -m venv ".venv"
if errorlevel 1 goto failed
:check_python
"%BUILD_PYTHON%" -c "import struct, sys; sys.exit(0 if sys.version_info[:2] == (3, 13) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 (
    echo ERROR: Python 3.13 64-bit is required.
    goto failed
)
echo [1/2] Preparing build dependencies...
"%BUILD_PYTHON%" -m pip install --disable-pip-version-check -r requirements-build.txt
if errorlevel 1 goto failed
echo [2/2] Building the application and a single installer EXE...
set "PYINSTALLER_CONFIG_DIR=%CD%\build\.pyinstaller-cache"
"%BUILD_PYTHON%" tools\build_release.py %BUILD_RELEASE%
if errorlevel 1 goto failed
set "BUILD_EXIT_CODE=0"
echo.
echo Build complete. The installer path is printed above.
echo Nothing was installed, launched, tested, or uploaded.
goto finish
:missing_python
echo ERROR: Install Python 3.13 64-bit with its launcher first.
goto finish
:failed
echo.
echo BUILD FAILED. See the error above.
:finish
echo.
if not defined BUILD_NO_PAUSE pause
popd
exit /b %BUILD_EXIT_CODE%
