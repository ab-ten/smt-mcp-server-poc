rem @echo off -*- coding: cp932-dos; -*-
setlocal

REM Convert relative path to absolute path
for %%I in (.) do set ABS_PATH=%%~fI

set OPTIONS=-v "%~dp0\app:/app:ro"
if exist "%HOME%\smt-mcp-server-poc.env" (
  set OPTIONS=%OPTIONS% --env-file "%HOME%\smt-mcp-server-poc.env"
) else if exist "%~dp0\.env" (
  set OPTIONS=%OPTIONS% --env-file "%~dp0\.env"
)


docker run --rm -it --init %OPTIONS% -e MCP_ROOT=/workspace -v "%ABS_PATH%:/workspace:ro" --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m %* smt-local-files-mcp
