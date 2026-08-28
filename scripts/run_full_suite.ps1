$env:PYTHONPATH = 'C:\Users\sujay\Downloads\hermes'
Set-Location 'C:\Users\sujay\Downloads\hermes'
& "C:\Program Files\Python311\python.exe" -m pytest tests -q --timeout=300 2>&1 | Out-File -FilePath reports\full_suite_explanation.txt -Encoding utf8
