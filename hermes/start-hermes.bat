@echo off
set "HERMES_HOME=%~dp0"
cd /d "%HERMES_HOME%"
wt -d "%HERMES_HOME%" cmd /c "echo ============================================ && echo   Hermes - Interactive Mode && echo   Feishu/Lark Platform ENABLED && echo ============================================ && hermes.exe chat"
