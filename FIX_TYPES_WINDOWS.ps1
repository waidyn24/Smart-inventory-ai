$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$path = Join-Path $root 'frontend\components\DashboardApp.tsx'
if (-not (Test-Path -LiteralPath $path)) { throw "File not found: $path" }
$utf8 = New-Object System.Text.UTF8Encoding($false)
$content = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
$old = 'const categories=[...new Set(products.map((p:Product)=>p.category))];'
$new = 'const categories: string[] = [...new Set<string>(products.map((p:Product)=>p.category))];'
if ($content.Contains($old)) {
  [System.IO.File]::WriteAllText($path, $content.Replace($old, $new), $utf8)
  Write-Host 'Patched DashboardApp.tsx' -ForegroundColor Green
} elseif ($content.Contains($new)) {
  Write-Host 'DashboardApp.tsx is already patched.' -ForegroundColor Green
} else { throw 'Expected code not found. This may be a different project version.' }
