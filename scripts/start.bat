@echo off
REM Khoi dong code-memory + mo trinh duyet
cd /d "%~dp0.."

REM Uu tien venv rieng cua repo, neu khong co thi dung venv Ollama (da co chromadb/torch/ollama)
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=C:\Agent\Agent_Ollama\Ollama\.venv\Scripts\python.exe"

REM Mo trinh duyet sau 3 giay (cho server kip khoi dong)
start "" powershell -WindowStyle Hidden -Command "Start-Sleep 3; Start-Process 'http://127.0.0.1:8077'"

"%PY%" -m codemem.api.server
