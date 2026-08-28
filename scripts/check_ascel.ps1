try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/projects/project:ascel_-_copy/intelligence?limit=20' -UseBasicParsing -TimeoutSec 15
    $r.Content | Out-File -FilePath reports\ascel_intel.json -Encoding utf8
    Write-Output ('LEN: ' + $r.Content.Length)
    Write-Output $r.Content.Substring(0, [Math]::Min(1500, $r.Content.Length))
} catch {
    Write-Output ('ERR: ' + $_.Exception.Message)
}
