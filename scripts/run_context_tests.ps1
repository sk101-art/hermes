$env:PYTHONPATH = 'C:\Users\sujay\Downloads\hermes'
Set-Location 'C:\Users\sujay\Downloads\hermes'
& "C:\Program Files\Python311\python.exe" -m pytest tests\test_context.py -v 2>&1 | Out-File -FilePath reports\context_after_fix.txt -Encoding utf8
