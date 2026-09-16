@echo off
setlocal
set "REPO=%~dp0..\.."
for %%I in ("%REPO%") do set "REPO=%%~fI"
set "PYTHONPATH=%REPO%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
if not defined UV_PYTHON_INSTALL_DIR set "UV_PYTHON_INSTALL_DIR=%REPO%\.python"
if not defined AGENTCAD_PROJECTS_DIR set "AGENTCAD_PROJECTS_DIR=%REPO%\projects"
if not defined AGENTCAD_AGENT_ID set "AGENTCAD_AGENT_ID=stella-mcp"
set "PY=%REPO%\agentcad-for-windows\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo stella-mcp: missing AgentCAD venv. Run scripts\stella\setup.ps1 1>&2
  exit /b 1
)
"%PY%" -m stella_cad.mcp
exit /b %ERRORLEVEL%
