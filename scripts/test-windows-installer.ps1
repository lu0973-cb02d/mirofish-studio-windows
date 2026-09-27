# This destructive installation test runs only on a disposable GitHub runner.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Run this installation test on a disposable GitHub Actions runner.' }
$version = (Get-Content 'desktop/package.json' -Raw | ConvertFrom-Json).version
$testRoot = Join-Path $env:RUNNER_TEMP 'mirofish-installer-qa'
$installRoot = Join-Path $testRoot 'installed'
# Electron uses the Windows known folder rather than an overridden APPDATA.
# This runner is disposable; use its real user-data location for the assertion.
$appDataRoot = [Environment]::GetFolderPath('ApplicationData')
$installer = (Resolve-Path "dist-installers/full/MiroFish-Studio-Full-$version-Setup.exe").Path
$install = Start-Process -FilePath $installer -ArgumentList @('/S',"/D=$installRoot") -WindowStyle Hidden -Wait -PassThru
if ($install.ExitCode -ne 0) { throw "Installer exited with $($install.ExitCode)" }
$exe = Join-Path $installRoot 'MiroFish Studio（全量版）.exe'
if (!(Test-Path -LiteralPath $exe)) { throw 'Installed executable is missing' }
$app = Start-Process -FilePath $exe -WindowStyle Hidden -PassThru
try {
  $health = $null
  for ($i = 0; $i -lt 90; $i++) {
    try { $health = Invoke-RestMethod 'http://127.0.0.1:3888/studio-health' -TimeoutSec 2; break } catch { Start-Sleep -Seconds 1 }
  }
  if (!$health -or $health.service -ne 'MiroFish Studio' -or $health.version -ne $version) { throw 'Installed service health check failed' }
  foreach ($endpoint in @('/','/icon.png')) {
    $response = Invoke-WebRequest "http://127.0.0.1:3888$endpoint" -TimeoutSec 10
    if ($response.StatusCode -ne 200) { throw "Page check failed: $endpoint" }
  }
  $expectedPython = [IO.Path]::GetFullPath((Join-Path $installRoot 'resources/mirofish/runtime/python.exe'))
  $python = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.ExecutablePath -eq $expectedPython }
  if (!$python) { throw 'Installed app did not use the bundled Python runtime' }
  if (Test-Path (Join-Path $installRoot 'resources/mirofish/studio_data')) { throw 'User data was written inside the program directory' }
  Write-Output "Installed full package $version passed service, UI, icon and bundled-runtime checks."
} finally {
  try { Invoke-RestMethod 'http://127.0.0.1:3888/studio-api/quit' -Method Post -ContentType 'application/json' -Headers @{'X-MiroFish-Studio'='1'} -Body '{}' -TimeoutSec 5 | Out-Null } catch {}
  Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($installRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
$dataRoot = Join-Path $appDataRoot 'mirofish-studio-desktop/data'
if (!(Test-Path -LiteralPath (Join-Path $dataRoot 'studio_data/desktop.log'))) { throw 'Actual desktop log is missing from the expected user data directory' }
$sentinel = Join-Path $dataRoot 'qa-preserve.txt'
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
Set-Content -LiteralPath $sentinel -Value 'Preserve user data during uninstall' -Encoding utf8
$before = (Get-FileHash -LiteralPath $sentinel).Hash
$uninstaller = Join-Path $installRoot 'Uninstall MiroFish Studio（全量版）.exe'
$uninstall = Start-Process -FilePath $uninstaller -ArgumentList '/S' -WindowStyle Hidden -Wait -PassThru
if ($uninstall.ExitCode -ne 0) { throw "Uninstaller exited with $($uninstall.ExitCode)" }
for ($i = 0; $i -lt 30 -and (Test-Path -LiteralPath $exe); $i++) { Start-Sleep -Seconds 1 }
if (Test-Path -LiteralPath $exe) { throw 'Uninstaller left the application executable' }
if (!(Test-Path -LiteralPath $sentinel) -or (Get-FileHash -LiteralPath $sentinel).Hash -ne $before) { throw 'Uninstaller did not preserve user data' }
Write-Output 'Uninstall passed and preserved user data.'
