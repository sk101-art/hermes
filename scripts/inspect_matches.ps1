$env:PYTHONPATH = 'C:\Users\sujay\Downloads\hermes'
Set-Location 'C:\Users\sujay\Downloads\hermes'
& "C:\Program Files\Python311\python.exe" scripts\inspect_matches.py 2>&1 | Out-File -FilePath reports\inspect_matches.txt -Encoding utf8
