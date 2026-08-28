$conn = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    Write-Output ('FRONTEND RUNNING PID ' + $conn.OwningProcess)
} else {
    Write-Output 'FRONTEND NOT RUNNING'
}
