$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*pytest*' }
if ($procs) {
    foreach ($p in $procs) {
        Write-Output ('PYTEST RUNNING PID ' + $p.ProcessId + ' created ' + $p.CreationDate)
    }
} else {
    Write-Output 'NO PYTEST PROCESS'
}
