# Apply every local patch, oldest first. Safe to re-run: an already applied
# patch is reported as "already applied" instead of failing.
#
#   .\apply.ps1                          # everything
#   .\apply.ps1 -Skip 0001,0002,0005     # client-only build (desktop, no server code)
#   .\apply.ps1 -Skip "0001 0002 0005"   # same, space separated
#
# Windows note: git rewrites these patch files to CRLF when `core.autocrlf=true`
# (the default on GitHub's Windows runners), and a CRLF patch cannot match LF
# source lines — every hunk fails with "patch does not apply". This script
# normalises each patch back to LF in place and applies with --ignore-whitespace,
# so it works on a fresh Windows clone without asking the user to fix git config.
param(
  [string]$Skip = ''
)

$ErrorActionPreference = 'Continue'
Set-Location (Join-Path $PSScriptRoot '..')

$skipSet = @($Skip -split '[,;\s]+' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$failed = @()
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

Get-ChildItem -Path (Join-Path $PSScriptRoot '0*-*.patch') | Sort-Object Name | ForEach-Object {
  $name = $_.Name
  if ($skipSet -contains $name.Substring(0, 4)) {
    "  skipped   $name"
    return
  }

  $text = [System.IO.File]::ReadAllText($_.FullName)
  if ($text.Contains("`r`n")) {
    [System.IO.File]::WriteAllText($_.FullName, ($text -replace "`r`n", "`n"), $utf8NoBom)
  }

  git apply --check --ignore-whitespace $_.FullName 2>$null
  if ($LASTEXITCODE -eq 0) {
    git apply --ignore-whitespace $_.FullName
    if ($LASTEXITCODE -eq 0) { "  ok        $name" } else { "  FAILED    $name"; $failed += $name }
    return
  }

  git apply --check --reverse --ignore-whitespace $_.FullName 2>$null
  if ($LASTEXITCODE -eq 0) {
    "  skip(re)  $name"
    return
  }

  $detail = (git apply --3way --ignore-whitespace $_.FullName 2>&1 | Out-String).Trim()
  "  CONFLICT  $name"
  if ($detail) { $detail -split "`n" | Select-Object -First 6 | ForEach-Object { "            $($_.Trim())" } }
  $failed += $name
}

if ($failed.Count -gt 0) {
  ''
  "Conflicts in: $($failed -join ', ')"
  "Resolve with 'git diff', then build. Nothing was committed."
  exit 1
}
