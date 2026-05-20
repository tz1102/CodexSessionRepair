param(
    [Parameter(Position = 0)]
    [ValidateSet("open", "list", "doctor", "repair", "delete")]
    [string]$Command = "open",

    [Parameter(Position = 1)]
    [string]$ThreadId = "",

    [string]$CodexHome = "$HOME\.codex",
    [int]$Port = 8787,
    [switch]$NoBrowser,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = Join-Path $root "src"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @("--codex-home", $CodexHome, $Command)
if ($Command -eq "open") {
    $argsList += @("--port", $Port)
    if ($NoBrowser) {
        $argsList += "--no-browser"
    }
}
if ($Command -eq "delete") {
    if (-not $ThreadId) {
        throw "delete 需要线程 ID。"
    }
    $argsList += $ThreadId
    if ($Yes) {
        $argsList += "--yes"
    }
}

python -m codex_local @argsList
