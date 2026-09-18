rem @echo off -*- coding: cp932-dos; -*-
setlocal

REM Convert relative path to absolute path
for %%I in (.) do set ABS_PATH=%%~fI

set OPTIONS=-v "%~dp0\app:/app:ro"

if exist "%~dp0\env_local.cmd" call "%~dp0\env_local.cmd"
if defined WORKFLOW_PATH set OPTIONS=%OPTIONS% --mount "type=bind,src=%WORKFLOW_PATH%,dst=/workflow,readonly"

if exist "%HOME%\smt-mcp-server-poc.env" (
  set OPTIONS=%OPTIONS% --env-file "%HOME%\smt-mcp-server-poc.env"
) else if exist "%~dp0\.env" (
  set OPTIONS=%OPTIONS% --env-file "%~dp0\.env"
)

if "%~1"=="--list" (
  docker run --rm %OPTIONS% -e MCP_ROOT=/workspace -v "%ABS_PATH%:/workspace:ro" --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m --entrypoint python smt-local-files-mcp /app/server.py --list
  exit /b %ERRORLEVEL%
)

for %%D in ("%CD%") do title MCP: %%~nxD
docker run --rm -it --init %OPTIONS% -e MCP_ROOT=/workspace -v "%ABS_PATH%:/workspace:ro" --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m %* smt-local-files-mcp
