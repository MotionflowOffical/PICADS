# PICADS Docker/WSL physical-backend diagnostics. READ-ONLY.
# No installs, Docker pruning, WSL unregistering or configuration changes.
param([string]$Distribution = 'Ubuntu')
$ErrorActionPreference = 'Continue'
Write-Host "PICADS physical backend diagnostics (read-only)" -ForegroundColor Cyan
Write-Host "WSL distro: $Distribution"
$tests = @(
    @{ Name = 'Windows Docker engine'; Command = @('docker', 'info') },
    @{ Name = 'Ubuntu Docker direct'; Command = @('wsl.exe', '--distribution', $Distribution, '--exec', 'docker', 'info') },
    @{ Name = 'Ubuntu Docker from PICADS login shell'; Command = @('wsl.exe', '--distribution', $Distribution, '--exec', 'bash', '-lc', 'docker info') },
    @{ Name = 'Ubuntu LibreLane Python environment'; Command = @('wsl.exe', '--distribution', $Distribution, '--exec', 'bash', '-lc', 'test -x "$HOME/.local/share/picads-librelane/venv/bin/python" && "$HOME/.local/share/picads-librelane/venv/bin/python" -c "import librelane"') }
)
foreach ($t in $tests) {
    Write-Host "`n--- $($t.Name) ---" -ForegroundColor Yellow
    $cmd = $t.Command
    $exe = $cmd[0]
    $rest = @($cmd | Select-Object -Skip 1)
    try {
        & $exe @rest 2>&1 | Select-Object -Last 60 | Out-Host
        $rc = $LASTEXITCODE
        Write-Host "Exit code: $rc"
    } catch {
        Write-Host "Cannot run command: $($_.Exception.Message)"
    }
}
Write-Host "`nNo system changes were made."
