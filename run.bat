@echo off
echo ================================================================
echo   Smart Inpatient Monitoring ^& Clinical Decision Support System
echo ================================================================
echo.

REM ── Try to compile C engine ──────────────────────────────────────
set "GCC_PATH=gcc"
where gcc >nul 2>&1
if %errorlevel% neq 0 (
    if exist "%USERPROFILE%\Downloads\mingw64\bin\gcc.exe" (
        set "GCC_PATH=%USERPROFILE%\Downloads\mingw64\bin\gcc.exe"
        set "PATH=%USERPROFILE%\Downloads\mingw64\bin;%PATH%"
    ) else (
        echo [INFO] GCC not found. Using Python fallback.
        echo        To use the C engine, install MinGW-w64 and add to PATH.
        echo.
        goto PYTHON_FALLBACK
    )
)

echo [1/4] Compiling C engine (triage.c)...
"%GCC_PATH%" -Wall -Wextra -std=c99 -O2 -o triage.exe triage.c -lm
if %errorlevel% neq 0 (
    echo [ERROR] Compilation failed. Falling back to Python.
    goto PYTHON_FALLBACK
)
echo [OK]  triage.exe compiled.
echo.

echo [2/4] Running C engine...
triage.exe patients.csv results.csv doctors.csv wards.csv history.csv
if %errorlevel% neq 0 (
    echo [ERROR] C engine failed. Falling back to Python.
    goto PYTHON_FALLBACK
)
goto COPY

:PYTHON_FALLBACK
echo [2/4] Running Python fallback (generate_results.py)...
python generate_results.py
if %errorlevel% neq 0 (
    echo [ERROR] Python also failed. Install Python from https://python.org
    pause
    exit /b 1
)

:COPY
echo.
echo [3/4] Copying output files to dashboard...
if exist results.csv copy /Y results.csv dashboard\results.csv >nul
if exist doctors.csv copy /Y doctors.csv dashboard\doctors.csv >nul
if exist wards.csv   copy /Y wards.csv   dashboard\wards.csv   >nul
if exist history.csv copy /Y history.csv dashboard\history.csv >nul
echo [OK]  Dashboard CSVs updated.
echo.

echo [4/4] Starting dashboard server...
echo       Open http://localhost:7890 in your browser.
echo       Press Ctrl+C in this window to stop.
echo.
echo ================================================================
echo   DONE!  Dashboard: http://localhost:7890
echo ================================================================
echo.
python server.py
pause
