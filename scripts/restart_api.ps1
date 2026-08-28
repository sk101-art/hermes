Set-Location 'C:\Users\sujay\Downloads\hermes'
$conn = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    Write-Output ('Stopping API server PID ' + $conn.OwningProcess + '...')
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
} else {
    Write-Output 'No API server listening on 8765.'
}
Write-Output 'Starting new API server...'
$env:PYTHONPATH = 'C:\Users\sujay\Downloads\hermes'
Start-Process -FilePath 'C:\Program Files\Python311\python.exe' -ArgumentList '-m','app.api.server','--port','8765' -WorkingDirectory 'C:\Users\sujay\Downloads\hermes' -WindowStyle Hidden
Start-Sleep -Seconds 10
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/health' -UseBasicParsing -TimeoutSec 10
    Write-Output ('HEALTH: ' + $r.Content)
} catch {
    Write-Output ('HEALTH ERR: ' + $_.Exception.Message)
}
try {
    $r2 = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/openapi.json' -UseBasicParsing -TimeoutSec 10
    $json = $r2.Content | ConvertFrom-Json
    $paths = $json.paths.PSObject.Properties.Name
    $match = $paths | Where-Object { $_ -like '*matches*' }
    if ($match) {
        Write-Output ('ROUTE FOUND: ' + ($match -join ', '))
    } else {
        Write-Output 'ROUTE STILL NOT FOUND'
    }
} catch {
    Write-Output ('OPENAPI ERR: ' + $_.Exception.Message)
}
