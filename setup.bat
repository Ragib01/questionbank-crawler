@echo off
echo =========================================
echo  Bangladesh Question Bank Crawler Setup
echo =========================================
echo.

echo [1/5] Installing uv (if not already installed)...
pip install uv --quiet
if errorlevel 1 (
    echo ERROR: pip install uv failed. Make sure Python is installed and in PATH.
    pause
    exit /b 1
)

echo.
echo [2/5] Creating local virtual environment (.venv)...
uv venv .venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

echo.
echo [3/5] Installing packages into .venv...
uv pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Package installation failed.
    pause
    exit /b 1
)

echo.
echo [4/5] Installing Playwright Chromium browser...
.venv\Scripts\playwright.exe install chromium
if errorlevel 1 (
    echo WARNING: Playwright browser install failed.
)

echo.
echo [5/5] Creating output directories and .env file...
if not exist "output\pdfs"       mkdir "output\pdfs"
if not exist "output\questions"  mkdir "output\questions"
if not exist "output\logs"       mkdir "output\logs"

if not exist ".env" (
    copy .env.example .env
    echo Created .env — please add your ANTHROPIC_API_KEY.
) else (
    echo .env already exists, skipping.
)

echo.
echo =========================================
echo  Setup complete!
echo =========================================
echo.
echo To run the app:
echo   .venv\Scripts\activate
echo   streamlit run app.py
echo.
echo Or use the run.bat shortcut.
echo.
pause
