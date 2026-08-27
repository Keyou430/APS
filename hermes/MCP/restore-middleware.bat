@echo off
chcp 65001 >nul 2>&1
echo ============================================
echo   Restore middleware + MCP dual mode
echo ============================================
echo.
echo [1/2] Enable three-source-retrieval middleware...
D:\Replica1.0\hermes\hermes.exe plugins enable three-source-retrieval
echo.
echo [2/2] Enable hermes-mcp tool...
D:\Replica1.0\hermes\hermes.exe plugins enable hermes-mcp
echo.
echo ============================================
echo   Done. Both links active.
echo     three-source-retrieval: auto-inject each turn
echo     hermes-mcp:            on-demand MCP tool
echo ============================================
pause
