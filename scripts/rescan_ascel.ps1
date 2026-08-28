$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*app.runtime.runner*' }
foreach ($p in $procs) {
    Write-Output ('Stopping daemon PID ' + $p.ProcessId)
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3
$env:PYTHONPATH = 'C:\Users\sujay\Downloads\hermes'
Set-Location 'C:\Users\sujay\Downloads\hermes'
& "C:\Program Files\Python311\python.exe" -m app.runtime.runner --job context_match 2>&1 | Out-File -FilePath reports\rescan_ascel.txt -Encoding utf8
Write-Output 'Rescan finished. Restarting daemon...'
Start-Process -FilePath 'C:\Program Files\Python311\python.exe' -ArgumentList '-m','app.runtime.runner' -WorkingDirectory 'C:\Users\sujay\Downloads\hermes' -WindowStyle Hidden
Write-Output 'Daemon restarted.'
