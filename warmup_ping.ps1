# Clinic system warmup ping
# Runs silently at login via Task Scheduler.
# Waits for the server to finish its internal warmup, then pre-fetches the
# report so the first nurse visit is instant.

$url = "http://localhost:8000"
$maxWait = 300   # seconds to wait for server to come up
$elapsed = 0

# Wait until the server is accepting connections
while ($elapsed -lt $maxWait) {
    try {
        $null = Invoke-WebRequest -Uri "$url/api/report" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        break
    } catch {
        Start-Sleep -Seconds 10
        $elapsed += 10
    }
}

# Hit the main endpoints so Supabase query results are cached
$endpoints = @(
    "/api/report",
    "/api/blood-pending"
)
foreach ($ep in $endpoints) {
    try { $null = Invoke-WebRequest -Uri "$url$ep" -UseBasicParsing -TimeoutSec 30 -ErrorAction SilentlyContinue } catch {}
}
