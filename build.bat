@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 exit /b 1
set "BUILD_EXIT_CODE=1"
set "BUILD_PYTHON=%CD%\.venv\Scripts\python.exe"
set "PYTHONUTF8=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"

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
    echo ERROR: This project requires Python 3.13 64-bit. Check the .venv environment.
    goto failed
)
echo [1/2] Preparing build dependencies...
"%BUILD_PYTHON%" -m pip install --disable-pip-version-check -r requirements-build.txt
if errorlevel 1 goto failed

echo [2/2] Building FileSearch.exe from current source...
echo Close any running dist\FileSearch\FileSearch.exe before rebuilding.
set "PYINSTALLER_CONFIG_DIR=%CD%\build\.pyinstaller-cache"
"%BUILD_PYTHON%" -m PyInstaller --clean --noconfirm --distpath "%CD%\dist" --workpath "%CD%\build" "FileSearch.spec"
if errorlevel 1 goto failed
if not exist "dist\FileSearch\FileSearch.exe" goto failed
set "BUILD_EXIT_CODE=0"
echo.
echo Build completed: "%CD%\dist\FileSearch\FileSearch.exe"
echo Keep the entire dist\FileSearch folder together, including _internal.
goto finish

:missing_python
echo ERROR: Python 3.13 was not found.
echo Install Python 3.13 64-bit with its launcher, or prepare .venv as described in README.md.
goto finish

:failed
echo.
echo BUILD FAILED. See the error above. Close the running EXE before trying again.

:finish
echo.
if /I not "%~1"=="--no-pause" pause
popd
exit /b %BUILD_EXIT_CODE%
