@echo off
chcp 65001 >nul 2>&1
echo ============================================
echo   Switch to MCP-only mode
echo ============================================
echo.
echo [1/2] Disable three-source-retrieval middleware...
D:\Replica1.0\hermes\hermes.exe plugins disable three-source-retrieval
echo.
echo [2/2] Enable hermes-mcp tool...
D:\Replica1.0\hermes\hermes.exe plugins enable hermes-mcp
echo.
echo ============================================
echo   Done. Start Hermes to test MCP link:
echo     D:\Replica1.0\hermes\start-hermes.bat
echo.
echo   Ask the AI: "search knowledge base for FastGPT"
echo.
echo   To restore: D:\Replica1.0\hermes\MCP\restore-middleware.bat
echo ============================================
pause
