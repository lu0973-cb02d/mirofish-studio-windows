param(
  [ValidateSet('control-panel','full','both')][string]$Variant = 'both',
  [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Stage = Join-Path $Root 'packaging\stage'
$Dist = Join-Path $Root 'dist\windows'
Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'control'), (Join-Path $Stage 'full') | Out-Null
Set-Content -LiteralPath (Join-Path $Stage 'control\.keep') -Value 'Control panel intentionally uses an existing local MiroFish Studio service.' -Encoding UTF8

function Copy-Tree([string]$Source, [string]$Target, [string[]]$ExcludeDirs = @()) {
  if (!(Test-Path -LiteralPath $Source)) { throw "缺少构建输入: $Source" }
  New-Item -ItemType Directory -Force -Path $Target | Out-Null
  $args = @($Source, $Target, '/E', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/XF', '.env', '*.log', '*.zip', '*.sqlite', '*.db', '*.pyc')
  foreach ($dir in $ExcludeDirs) { $args += '/XD'; $args += (Join-Path $Source $dir) }
  & robocopy @args | Out-Null
  if ($LASTEXITCODE -gt 7) { throw "复制失败: $Source (robocopy $LASTEXITCODE)" }
}

if ($Variant -in @('full','both')) {
  Copy-Tree (Join-Path $Root 'local_studio') (Join-Path $Stage 'full\local_studio')
  Copy-Tree (Join-Path $Root 'backend') (Join-Path $Stage 'full\backend') @('uploads','logs','__pycache__','.pytest_cache')
  Copy-Tree (Join-Path $Root 'frontend\dist') (Join-Path $Stage 'full\frontend\dist')
  Copy-Tree (Join-Path $Root 'static') (Join-Path $Stage 'full\static')
  Copy-Tree (Join-Path $Root 'locales') (Join-Path $Stage 'full\locales')
  $venv = Join-Path $Root 'backend\.venv'
  if (!(Test-Path -LiteralPath $venv)) { throw "全量版需要 backend/.venv；先运行 npm run setup:backend 或使用 -Variant control-panel。" }
  $size = (Get-ChildItem -LiteralPath $Stage\full -Recurse -File | Measure-Object Length -Sum).Sum
  Write-Host ("全量版 staging 大小: {0:N1} MB" -f ($size / 1MB))
}

if ($SkipBuild) { Write-Host "已完成 staging，跳过 electron-builder。"; exit 0 }
$builder = Join-Path $Root 'node_modules\.bin\electron-builder.cmd'
if (!(Test-Path -LiteralPath $builder)) { throw '未找到 electron-builder。运行 npm install 后再执行此脚本。' }
New-Item -ItemType Directory -Force -Path $Dist | Out-Null
if ($Variant -in @('control-panel','both')) { & $builder --config packaging/electron-builder.control-panel.yml; if ($LASTEXITCODE -ne 0) { throw '控制面板版构建失败。' } }
if ($Variant -in @('full','both')) { & $builder --config packaging/electron-builder.full.yml; if ($LASTEXITCODE -ne 0) { throw '全量版构建失败。' } }
Write-Host 'Windows 打包完成。请检查 dist/windows 下的 NSIS 与 portable 产物。'
