# setup-r1a-keys.ps1 — Interactive helper to set R1A API key env vars.
# Path B v1.11.s49 (2026-05-11).
#
# Usage:
#   pwsh ./scripts/setup-r1a-keys.ps1            # interactive prompt
#   pwsh ./scripts/setup-r1a-keys.ps1 -List      # just show current state
#   pwsh ./scripts/setup-r1a-keys.ps1 -Scope User  # write to User env (persists)
#
# Default scope: Process (current shell only). Use -Scope User to make
# permanent for your Windows account.

[CmdletBinding()]
param(
    [switch]$List,
    [ValidateSet("Process", "User")]
    [string]$Scope = "Process"
)

# Provider catalog — kept in sync with `python -m assetboy.cli gen list-providers`.
$Providers = @(
    @{
        Id = "pexels"; EnvVar = "PEXELS_API_KEY"
        Signup = "https://www.pexels.com/api/new/"
        License = "Pexels License (free personal+commercial)"
        Description = "Stock photos + VIDEOS"
    },
    @{
        Id = "pixabay"; EnvVar = "PIXABAY_API_KEY"
        Signup = "https://pixabay.com/api/docs/"
        License = "CC0-equivalent (Pixabay Content License)"
        Description = "Photos + illustrations + vectors + videos"
    },
    @{
        Id = "unsplash"; EnvVar = "UNSPLASH_ACCESS_KEY"
        Signup = "https://unsplash.com/developers"
        License = "Unsplash License (free personal+commercial)"
        Description = "High-quality stock photography"
    },
    @{
        Id = "rawg"; EnvVar = "RAWG_API_KEY"
        Signup = "https://rawg.io/apidocs"
        License = "REFERENCE-ONLY (publisher copyright)"
        Description = "Game DB (covers + screenshots)"
    },
    @{
        Id = "jamendo"; EnvVar = "JAMENDO_CLIENT_ID"
        Signup = "https://developer.jamendo.com/"
        License = "CC-BY / CC-BY-SA (commercial-OK by default)"
        Description = "CC music tracks (~500K)"
    }
)

function Show-CurrentState {
    Write-Host ""
    Write-Host "===== R1A API key state =====" -ForegroundColor Cyan
    Write-Host ""
    $setCount = 0
    foreach ($p in $Providers) {
        $value = [Environment]::GetEnvironmentVariable($p.EnvVar, "Process")
        $userValue = [Environment]::GetEnvironmentVariable($p.EnvVar, "User")
        $hasProcess = -not [string]::IsNullOrWhiteSpace($value)
        $hasUser = -not [string]::IsNullOrWhiteSpace($userValue)

        $status = ""
        if ($hasProcess -and $hasUser) {
            $status = "PROCESS + USER (both set)"
            $color = "Green"
            $setCount++
        }
        elseif ($hasProcess) {
            $status = "PROCESS only (this shell)"
            $color = "Yellow"
            $setCount++
        }
        elseif ($hasUser) {
            $status = "USER only (load by restarting shell)"
            $color = "Yellow"
            $setCount++
        }
        else {
            $status = "UNSET"
            $color = "Red"
        }

        Write-Host ("  {0,-22} ${1,-22} {2}" -f $p.Id, $p.EnvVar, $status) -ForegroundColor $color
    }
    Write-Host ""
    Write-Host "  Set: $setCount / $($Providers.Count)" -ForegroundColor $(if ($setCount -eq $Providers.Count) { "Green" } else { "Yellow" })
    Write-Host ""
}

function Prompt-ForKey {
    param(
        [hashtable]$Provider,
        [string]$Scope
    )
    $currentProcess = [Environment]::GetEnvironmentVariable($Provider.EnvVar, "Process")
    $currentUser = [Environment]::GetEnvironmentVariable($Provider.EnvVar, "User")

    Write-Host ""
    Write-Host ("== {0} ({1}) ==" -f $Provider.Id, $Provider.EnvVar) -ForegroundColor Cyan
    Write-Host "  License: $($Provider.License)" -ForegroundColor Gray
    Write-Host "  What:    $($Provider.Description)" -ForegroundColor Gray
    Write-Host "  Signup:  $($Provider.Signup)" -ForegroundColor Gray
    Write-Host ""

    if ($currentProcess) {
        Write-Host "  Currently set in this shell (Process scope)." -ForegroundColor Yellow
    }
    if ($currentUser) {
        Write-Host "  Currently set in User scope (persists)." -ForegroundColor Yellow
    }

    $existing = if ($currentProcess) { $currentProcess } elseif ($currentUser) { $currentUser } else { "" }
    $prompt = "  Enter $($Provider.EnvVar) (blank to skip"
    if ($existing) {
        $prompt += ", 'clear' to unset"
    }
    $prompt += "): "
    $answer = Read-Host $prompt

    if ([string]::IsNullOrWhiteSpace($answer)) {
        Write-Host "  (skipped)" -ForegroundColor Gray
        return
    }
    if ($answer.Trim().ToLower() -eq "clear") {
        [Environment]::SetEnvironmentVariable($Provider.EnvVar, $null, $Scope)
        Write-Host "  Cleared (scope: $Scope)." -ForegroundColor Yellow
        return
    }
    [Environment]::SetEnvironmentVariable($Provider.EnvVar, $answer.Trim(), $Scope)
    Write-Host "  Set $($Provider.EnvVar) in $Scope scope." -ForegroundColor Green
    if ($Scope -eq "User") {
        Write-Host "  Restart your shell for it to take effect in new sessions." -ForegroundColor Gray
    }
}

# Banner.
Write-Host ""
Write-Host "===== FAW R1A API Key Setup =====" -ForegroundColor Cyan
Write-Host ""
Write-Host "5 R1A providers require API keys (all free signup)." -ForegroundColor White
Write-Host "5 other R1A providers are no-key (Met/Wikimedia/Archive.org/Scryfall/Iconify)." -ForegroundColor Gray
Write-Host ""

if ($List) {
    Show-CurrentState
    exit 0
}

Show-CurrentState

if ($Scope -eq "User") {
    Write-Host "Writing to USER scope (persists across shells)." -ForegroundColor Yellow
}
else {
    Write-Host "Writing to PROCESS scope (this shell only; use -Scope User to persist)." -ForegroundColor Gray
}
Write-Host ""

foreach ($provider in $Providers) {
    Prompt-ForKey -Provider $provider -Scope $Scope
}

Write-Host ""
Write-Host "===== Final state =====" -ForegroundColor Cyan
Show-CurrentState

Write-Host "Verify in CLI:" -ForegroundColor White
Write-Host "  python -m assetboy.cli gen list-providers" -ForegroundColor White
Write-Host ""
Write-Host "Quick scout (uses configured keys; skips missing):" -ForegroundColor White
Write-Host "  python -m assetboy.cli gen all-key -q 'fire' --include-video --dry-run" -ForegroundColor White
Write-Host ""
