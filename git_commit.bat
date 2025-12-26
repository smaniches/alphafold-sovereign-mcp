@echo off
cd /d C:\Users\santi\Documents\GITHUB_REPOS\alphafold-sovereign-mcp
"C:\Program Files\Git\cmd\git.exe" status
echo.
echo === DIFF STAT ===
"C:\Program Files\Git\cmd\git.exe" diff --stat
echo.
echo === ADDING FILES ===
"C:\Program Files\Git\cmd\git.exe" add -A
echo.
echo === COMMITTING ===
"C:\Program Files\Git\cmd\git.exe" commit -m "fix: Dynamic cache architecture - cache-first strategy + unified index"
echo.
echo === PUSHING ===
"C:\Program Files\Git\cmd\git.exe" push origin main
echo.
echo === DONE ===
