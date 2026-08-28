$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*app.runtime.runner*' }
if ($procs) {
    foreach ($p in $procs) {
        Write-Output ('DAEMON PID: ' + $p.ProcessId + ' CmdLine: ' + $p.CommandLine)
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Output ('Stopped daemon PID ' + $p.ProcessId)
    }
} else {
    Write-Output 'NO DAEMON PROCESS FOUND'
}
Start-Sleep -Seconds 2
Set-Location 'C:\Users\sujay\Downloads\hermes'
$env:PYTHONPATH = 'C:\Users\sujay\Downloads\hermes'
Start-Process -FilePath 'C:\Program Files\Python311\python.exe' -ArgumentList '-m','app.runtime.runner' -WorkingDirectory 'C:\Users\sujay\Downloads\hermes' -WindowStyle Hidden
Write-Output 'New daemon started.'
