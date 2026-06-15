rem @echo off -*- coding: cp932-dos; -*-
setlocal

REM Convert relative path to absolute path
for %%I in (.) do set ABS_PATH=%%~fI

docker run --rm -it --init ^
  -w /workspace ^
  -e PYTHONPYCACHEPREFIX=/tmp/codex-pycache ^
  -v "%ABS_PATH%:/workspace:ro" ^
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m ^
  --entrypoint python ^
  smt-local-files-mcp ^
  -m unittest discover -s tests
