Set-Location $PSScriptRoot
.\venv\Scripts\activate.ps1
uvicorn main:app --port 8000
