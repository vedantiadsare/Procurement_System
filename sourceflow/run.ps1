<#
Samagra - one command to run everything.

    .\run.ps1            local only: links in supplier mails point at localhost
    .\run.ps1 -Tunnel    also opens a public tunnel, so suppliers anywhere can
                         open their links. Needs cloudflared.exe in Downloads.

What it does, in order:
  1. stops anything already listening on port 8000
  2. (with -Tunnel) starts cloudflared minimised, waits for its URL, and writes
     it to public_url.txt - the app reads that file, so no variables to set
  3. makes sure Ollama is running, so the local AI model is there as a fallback
  4. checks every feature for real - AI model, email, online prices, supplier
     links - and prints what to do about anything not ready. If LLMaaS was
     chosen but isn't answering (VPN off), this run uses the local model
  5. starts the server, without --reload, so agents can't be killed mid-run

Ctrl+C stops the server. The tunnel window stays open; close it when done.
#>
param([switch]$Tunnel)

Set-Location $PSScriptRoot

# 0. the AI settings as saved for this Windows user. A terminal - VS Code's
#    especially - keeps the values it was opened with, so a key or LLM_MODE
#    saved since then would otherwise be ignored and the run would quietly
#    stay on the local model.
foreach ($name in "LLM_MODE", "LLMAAS_BASE_URL", "LLMAAS_MODEL", "LLMAAS_API_KEY",
                  "LLMAAS_CLIENT_ID", "LLMAAS_CLIENT_SECRET", "OLLAMA_MODEL") {
    $saved = [Environment]::GetEnvironmentVariable($name, "User")
    if ($saved) { Set-Item "env:$name" $saved.Trim() }
}

# 1. a clean port. A --reload server is two processes, so kill the tree; and
#    a server started in another session (an admin window, VS Code) can't be
#    killed from here at all - say so, rather than failing later with a
#    cryptic "only one usage of each socket address".
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { taskkill /PID $_.OwningProcess /T /F 2>&1 | Out-Null }
Start-Sleep -Seconds 1
# If something still holds 8000 that this window can't kill, don't stop -
# take the next free port. The tunnel and the printed address follow it.
$Port = 8000
while (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { $Port++ }
if ($Port -ne 8000) {
    Write-Host "Port 8000 is held by an old server (PID $((Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess)) - using port $Port instead." -ForegroundColor Yellow
}

# 2. the tunnel
Remove-Item public_url.txt -ErrorAction SilentlyContinue
if ($Tunnel) {
    $exe = Join-Path $HOME "Downloads\cloudflared.exe"
    if (-not (Test-Path $exe)) {
        Write-Host "cloudflared.exe not found in Downloads - starting without a tunnel." -ForegroundColor Yellow
    } else {
        $log = Join-Path $env:TEMP "cloudflared.log"
        Remove-Item $log -ErrorAction SilentlyContinue
        # cloudflared prints its URL on stderr
        Start-Process -FilePath $exe -ArgumentList "tunnel --url http://localhost:$Port" `
            -RedirectStandardError $log -WindowStyle Minimized
        Write-Host "Starting tunnel..." -NoNewline
        $url = $null
        $until = (Get-Date).AddSeconds(45)
        while (-not $url -and (Get-Date) -lt $until) {
            Start-Sleep -Seconds 2
            Write-Host "." -NoNewline
            if (Test-Path $log) {
                $m = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
                if ($m) { $url = $m.Matches[0].Value }
            }
        }
        Write-Host ""
        if ($url) {
            $url | Set-Content public_url.txt -NoNewline
            Write-Host "Public URL: $url" -ForegroundColor Green
        } else {
            Write-Host "The tunnel didn't report a URL in 45s - links will use localhost." -ForegroundColor Yellow
        }
    }
}

# 3. the local model, running - the fallback whenever LLMaaS can't be reached
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
if ((Get-Command ollama -ErrorAction SilentlyContinue) -and
    -not (Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue)) {
    Write-Host "Starting Ollama..." -NoNewline
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    $until = (Get-Date).AddSeconds(20)
    while (-not (Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue) -and (Get-Date) -lt $until) {
        Start-Sleep -Milliseconds 500; Write-Host "." -NoNewline
    }
    Write-Host ""
}

# 4. is everything ready to show?
python tools/demo_check.py
if ($LASTEXITCODE -eq 3) { $env:LLM_MODE = "ollama" }

# 5. the server
Write-Host ""
Write-Host "Samagra is at http://localhost:$Port  (Ctrl+C to stop)" -ForegroundColor Cyan
uvicorn main:app --host 127.0.0.1 --port $Port
