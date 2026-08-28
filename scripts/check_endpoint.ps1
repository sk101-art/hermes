try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/projects/project:ascel_-_copy/matches/cluster:cd47d36d38c6' -UseBasicParsing -TimeoutSec 10
    Write-Output ('STATUS: ' + $r.StatusCode)
    Write-Output $r.Content.Substring(0, [Math]::Min(800, $r.Content.Length))
} catch {
    $resp = $_.Exception.Response
    if ($resp) {
        $stream = $resp.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $body = $reader.ReadToEnd()
        Write-Output ('CODE: ' + [int]$resp.StatusCode)
        Write-Output ('BODY: ' + $body)
    } else {
        Write-Output ('ERR: ' + $_.Exception.Message)
    }
}
