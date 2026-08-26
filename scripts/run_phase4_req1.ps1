Set-Location "C:\Users\sujay\Downloads\hermes"
& "C:\Program Files\Python311\python.exe" -m pytest tests/test_phase4_db_unification.py -x -q *>&1 | Out-File -Encoding utf8 reports\phase4_req1_check.txt
exit $LASTEXITCODE
