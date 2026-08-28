$conn = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $pid8765 = $conn[0].OwningProcess
    $proc = Get-Process -Id $pid8765 -ErrorAction SilentlyContinue
    Write-Output ('LISTENER PID: ' + $pid8765 + ' (' + $proc.ProcessName + ')')
    Write-Output ('Path: ' + $proc.Path)
    try {
        $cmdline = (Get-CimInstance Win32_Process -Filter ('ProcessId=' + $pid8765)).CommandLine
        Write-Output ('CmdLine: ' + $cmdline)
    } catch {
        Write-Output 'CmdLine: unavailable'
    }
} else {
    Write-Output 'NO LISTENER on 8765'
}
