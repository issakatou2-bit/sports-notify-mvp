# 本人の専用cloneのmainだけを更新してから実行。注文からコマンドを受け取らない。
param([string]$Python = 'C:\Users\issak\AppData\Local\Programs\Python\Python314\python.exe')
$ErrorActionPreference = 'Stop'
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'Never'
$taskRepo = Split-Path -Parent $PSScriptRoot
function Invoke-WorkerGit {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$GitArgs)
    # Windows PowerShell 5.1は成功したgitの進捗stderrもErrorRecordにする。
    # 詳細は捕捉し、終了コードだけで成否を判定する。
    $ErrorActionPreference = 'Continue'
    $taskGitOutput = & git -C $taskRepo @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'git' }
    return $taskGitOutput
}
$taskLock = New-Object System.Threading.Mutex($false, 'Local\CollespoUiVoiceWorker')
$taskAcquired = $false
try {
    try { $taskAcquired = $taskLock.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $taskAcquired = $true }
    if (-not $taskAcquired) { exit 0 }
    $taskBranch = Invoke-WorkerGit branch --show-current
    if ($taskBranch -ne 'main') { throw 'branch' }
    $taskOrigin = Invoke-WorkerGit remote get-url origin
    if ($taskOrigin -ne 'https://github.com/issakatou2-bit/sports-notify-mvp.git') { throw 'origin' }
    $taskDirty = Invoke-WorkerGit status --porcelain --untracked-files=normal
    if ($taskDirty) { throw 'dirty' }
    $taskPull = Invoke-WorkerGit pull --ff-only origin main
    # タスクサービスが古い環境を持っていても、本人の最新のユーザー変数を使う。
    $env:COLLESPO_UI_PARTS_KEY = [Environment]::GetEnvironmentVariable('COLLESPO_UI_PARTS_KEY', 'User')
    $taskApsc = [Environment]::GetEnvironmentVariable('COLLESPO_APSC_ROOT', 'User')
    if ($taskApsc) { $env:COLLESPO_APSC_ROOT = $taskApsc }
    Push-Location $taskRepo
    try {
        $ErrorActionPreference = 'Continue'
        & $Python (Join-Path $taskRepo 'scripts\ui_voice_worker.py')
        $taskCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = 'Stop'
        Pop-Location
    }
    exit $taskCode
} catch {
    # git出力や例外詳細は、認証値を含む可能性があるため表示しない。
    Write-Output 'Worker update failed. Check clean main, origin and Git connection.'
    exit 1
} finally {
    if ($taskAcquired) { $taskLock.ReleaseMutex() }
    $taskLock.Dispose()
}
