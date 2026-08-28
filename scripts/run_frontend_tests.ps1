Set-Location 'C:\Users\sujay\Downloads\hermes\frontend'
npm test 2>&1 | Out-File -FilePath '..\reports\frontend_explanation.txt' -Encoding utf8
