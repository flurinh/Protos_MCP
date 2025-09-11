@echo off
REM Batch file to run Protos MCP Server on Windows

REM Check if in conda environment
if "%CONDA_PREFIX%"=="" (
    echo Activating protos conda environment...
    call C:\Users\hidbe\miniconda\Scripts\activate.bat protos
)

REM Set Python path for Protos
set PYTHONPATH=%~dp0;%~dp0\protos\src;%PYTHONPATH%
set PROTOS_DATA_ROOT=%~dp0\protos\data

REM Install MCP if needed
echo Checking for MCP installation...
python -c "import mcp" 2>nul
if errorlevel 1 (
    echo Installing MCP...
    pip install mcp
)

REM Run the server
echo Starting Protos MCP Server...
python "%~dp0claude_server.py" %*