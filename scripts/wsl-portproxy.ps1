# PowerShell script to set up netsh portproxy for WSL2.
# Run as Administrator, e.g. via Task Scheduler at logon.
#
# This refreshes the portproxy rule each time because WSL's IP changes on reboot.

$WslIp = (wsl hostname -I).Trim().Split(" ")[0]
$Ports = @(9000)

foreach ($Port in $Ports) {
    # Remove existing rule (ignore errors if none exists)
    netsh interface portproxy delete v4tov4 listenport=$Port listenaddress=0.0.0.0 2>$null

    # Add new rule
    netsh interface portproxy add v4tov4 listenport=$Port listenaddress=0.0.0.0 connectport=$Port connectaddress=$WslIp

    Write-Host "Forwarding 0.0.0.0:$Port -> ${WslIp}:$Port"
}

# Ensure firewall rule exists
$RuleName = "yt-queue (WSL)"
$Existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if (-not $Existing) {
    New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -LocalPort $Ports -Protocol TCP -Action Allow
    Write-Host "Created firewall rule: $RuleName"
}
