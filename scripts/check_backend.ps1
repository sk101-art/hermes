try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/health' -UseBasicParsing -TimeoutSec 5
    Write-Output $r.Content
} catch {
    Write-Output ('ERR: ' + $_.Exception.Message)
}
