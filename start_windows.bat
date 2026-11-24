@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
call ".venv\Scripts\activate.bat"
python -m pip install -r requirements.txt
start "HuffmanX Backend" cmd /k "cd /d ""%~dp0backend"" && ""%~dp0.venv\Scripts\python.exe"" -m uvicorn main:app --reload --host 127.0.0.1 --port 8000"
start "HuffmanX Frontend" cmd /k "cd /d ""%~dp0frontend"" && ""%~dp0.venv\Scripts\python.exe"" -m http.server 5500 --bind 127.0.0.1"
echo.
echo Backend: http://127.0.0.1:8000
 echo Frontend: http://127.0.0.1:5500
 echo API docs: http://127.0.0.1:8000/docs
pause
