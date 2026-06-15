param(
    [int]$IntervalSeconds = 300
)

Write-Host "Starting Risk Manager Platform refresh loop. Interval: $IntervalSeconds seconds"
Write-Host "Set RMP_MARKET_API_URL / RMP_MARKET_API_KEY and RMP_NEWS_API_URL / RMP_NEWS_API_KEY when boss APIs are available."

while ($true) {
    python scripts\refresh_platform.py
    Start-Sleep -Seconds $IntervalSeconds
}
