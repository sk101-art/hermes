try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/openapi.json' -UseBasicParsing -TimeoutSec 10
    $json = $r.Content | ConvertFrom-Json
    $paths = $json.paths.PSObject.Properties.Name
    $match = $paths | Where-Object { $_ -like '*matches*' }
    if ($match) {
        Write-Output ('ROUTE FOUND: ' + ($match -join ', '))
    } else {
        Write-Output 'ROUTE NOT FOUND in openapi.json'
        Write-Output ('Total paths: ' + $paths.Count)
    }
} catch {
    Write-Output ('ERR: ' + $_.Exception.Message)
}
