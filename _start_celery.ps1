Set-Location $PSScriptRoot
.\venv\Scripts\activate.ps1
celery -A tasks.celery_app worker --loglevel=info --pool=solo
