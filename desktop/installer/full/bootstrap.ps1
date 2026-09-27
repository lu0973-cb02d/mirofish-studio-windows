param(
  [string]$InstallRoot = "$env:LOCALAPPDATA\MiroFish"
)

$ErrorActionPreference = "Stop"
$backend = Join-Path $InstallRoot "backend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"

function Find-Python {
  $commands = @("py", "python")
  foreach ($command in $commands) {
    $candidate = Get-Command $command -ErrorAction SilentlyContinue
    if ($candidate) { return $candidate.Source }
  }
  return $null
}

if (-not (Test-Path $venvPython)) {
  $python = Find-Python
  if (-not $python) {
    throw "未检测到 Python 3.11 或更高版本。请先安装 Python，并勾选加入 PATH，然后重新运行安装。"
  }
  New-Item -ItemType Directory -Force -Path $backend | Out-Null
  & $python -m venv (Join-Path $backend ".venv")
}

& $venvPython -m pip install --disable-pip-version-check --upgrade pip
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $backend "requirements.txt")
Write-Host "MiroFish 运行环境已准备：$InstallRoot"
