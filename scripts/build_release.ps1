[CmdletBinding()]
param(
    [switch]$Publish,
    [switch]$SkipTests,
    [switch]$SkipBuild,
    [switch]$InstallLocal,
    [switch]$SkipLocalInstall,
    [switch]$StaticOnly
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

try {
    $InstallDir = Join-Path $env:LOCALAPPDATA "Programs\AntigravityControlCenter"
    $InstalledExe = Join-Path $InstallDir "AntigravityControlCenter.exe"
    $CompanionScripts = @(
        "auto_patch_antigravity.js",
        "antigravity-drag-daemon.js",
        "antigravity_drag_daemon.pyw",
        "run_daemon.vbs",
        "start-drag-daemon.vbs"
    )

    function Stop-InstalledApp {
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:28795/api/daemon/quit" -Method Post -TimeoutSec 2 -ErrorAction SilentlyContinue | Out-Null
            Start-Sleep -Seconds 2
        }
        catch {
            # Ignore if daemon is not running
        }

        $RunningProcs = Get-Process -Name "AntigravityControlCenter" -ErrorAction SilentlyContinue
        if ($RunningProcs) {
            Write-Host "[Release] Stopping remaining AntigravityControlCenter.exe processes..." -ForegroundColor Yellow
            $RunningProcs | Stop-Process -Force -ErrorAction SilentlyContinue
            $RunningProcs | Wait-Process -Timeout 5 -ErrorAction SilentlyContinue
        }
    }

    function Start-InstalledAppDetached {
        $Launch = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = "`"$InstalledExe`"" }
        if ($Launch.ReturnValue -ne 0) {
            throw "Failed to relaunch installed app (Win32_Process Create returned $($Launch.ReturnValue))"
        }
    }

    function Sync-CompanionScripts {
        $ScriptsSrcDir = Join-Path $RepoRoot "scripts"
        foreach ($ScriptName in $CompanionScripts) {
            $SrcPath = Join-Path $ScriptsSrcDir $ScriptName
            if (Test-Path $SrcPath) {
                Copy-Item -Path $SrcPath -Destination (Join-Path $InstallDir $ScriptName) -Force
            }
        }
    }
    # 1. Read APP_VERSION from version.py
    $VersionFile = Join-Path $RepoRoot "version.py"
    if (-not (Test-Path $VersionFile)) {
        throw "version.py not found at $VersionFile"
    }
    $VersionContent = Get-Content -Path $VersionFile -Raw -Encoding UTF8
    $Match = [regex]::Match($VersionContent, 'APP_VERSION\s*=\s*["''](\d+\.\d+\.\d+)["'']')
    if (-not $Match.Success) {
        throw "Could not parse semantic APP_VERSION from version.py"
    }
    $Version = $Match.Groups[1].Value
    $Tag = "v$Version"
    Write-Host "[Release] Target version: $Version (tag $Tag)" -ForegroundColor Cyan

    # 2. Pre-publish git & GitHub CLI checks
    if ($Publish) {
        Write-Host "[Release] Running pre-publish safety checks..." -ForegroundColor Cyan
        $GitStatus = git status --porcelain
        if ($LASTEXITCODE -ne 0) {
            throw "git status failed"
        }
        if ($GitStatus) {
            throw "Working tree is not clean. Commit or stash changes before running -Publish."
        }

        gh auth status | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "GitHub CLI is not authenticated. Run 'gh auth login' first."
        }

        $LocalTag = git tag -l $Tag
        if ($LocalTag) {
            throw "Tag $Tag already exists locally."
        }
        $RemoteTag = git ls-remote --tags origin "refs/tags/$Tag"
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to query origin tags."
        }
        if ($RemoteTag) {
            throw "Tag $Tag already exists on origin."
        }
    }

    # 3. Run automated guardrail unit tests
    if (-not $SkipTests) {
        Write-Host "[Release] Running guardrail unit tests..." -ForegroundColor Cyan
        $PrevPythonPath = $env:PYTHONPATH
        try {
            $env:PYTHONPATH = ".;tests"
            python -m unittest test_release -v
            if ($LASTEXITCODE -ne 0) {
                throw "Unit tests failed with exit code $LASTEXITCODE"
            }
        }
        finally {
            $env:PYTHONPATH = $PrevPythonPath
        }
    }

    # 3b. Fast Path A: Static/script-only local sync (skips PyInstaller and Inno Setup)
    if ($InstallLocal -and $StaticOnly -and (-not $Publish) -and (Test-Path $InstalledExe)) {
        Write-Host "[Release] Fast-syncing static assets and companion scripts to $InstallDir..." -ForegroundColor Cyan
        Stop-InstalledApp

        $InternalDir = Join-Path $InstallDir "_internal"
        $TargetStaticDir = if (Test-Path $InternalDir) {
            Join-Path $InternalDir "static"
        } else {
            Join-Path $InstallDir "static"
        }
        New-Item -ItemType Directory -Force -Path $TargetStaticDir | Out-Null
        robocopy (Join-Path $RepoRoot "static") $TargetStaticDir /E /R:2 /W:1 /NP | Out-Host
        if ($LASTEXITCODE -ge 8) {
            throw "robocopy static sync failed with exit code $LASTEXITCODE"
        }

        Sync-CompanionScripts
        Start-InstalledAppDetached
        Write-Host "[Release] Fast static sync complete; app relaunched." -ForegroundColor Green
        return
    }

    # 4. Build PyInstaller bundle and verify critical artifacts
    $DistAppDir = Join-Path $RepoRoot "dist\AntigravityControlCenter"
    if (-not $SkipBuild) {
        Write-Host "[Release] Building PyInstaller bundle..." -ForegroundColor Cyan
        pyinstaller AntigravityControlCenter.spec --noconfirm
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller build failed with exit code $LASTEXITCODE"
        }
    }

    $BuiltExe = Join-Path $DistAppDir "AntigravityControlCenter.exe"
    $StaticIndexCandidates = @(
        (Join-Path $DistAppDir "_internal\static\index.html"),
        (Join-Path $DistAppDir "static\index.html")
    )
    $SslPydCandidates = @(
        (Join-Path $DistAppDir "_internal\_ssl.pyd"),
        (Join-Path $DistAppDir "_ssl.pyd")
    )

    if (-not (Test-Path $BuiltExe)) {
        throw "Missing PyInstaller output: $BuiltExe"
    }
    if (-not ($StaticIndexCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)) {
        throw "Missing bundled static\index.html in $DistAppDir"
    }
    if (-not ($SslPydCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)) {
        throw "Missing bundled _ssl.pyd in $DistAppDir (required for HTTPS updater)"
    }
    Write-Host "[Release] Verified PyInstaller bundle (exe, static\index.html, _ssl.pyd)" -ForegroundColor Green

    # 4b. Fast Path B: Local mirror sync without Inno Setup
    if ($InstallLocal -and (-not $StaticOnly) -and (-not $Publish) -and (Test-Path $InstalledExe)) {
        Write-Host "[Release] Mirror-syncing PyInstaller bundle to $InstallDir (skipping Inno Setup)..." -ForegroundColor Cyan
        Stop-InstalledApp

        robocopy $DistAppDir $InstallDir /MIR /R:2 /W:1 /NP /XF unins* | Out-Host
        if ($LASTEXITCODE -ge 8) {
            throw "robocopy bundle mirror failed with exit code $LASTEXITCODE"
        }

        Sync-CompanionScripts
        Start-InstalledAppDetached
        Write-Host "[Release] Local mirror sync complete; app relaunched." -ForegroundColor Green
        return
    }

    # 5. Locate ISCC.exe and compile Inno Setup 6 installer
    $IsccCmd = Get-Command iscc -ErrorAction SilentlyContinue
    $IsccPath = $null
    if ($IsccCmd) {
        $IsccPath = $IsccCmd.Source
    }
    else {
        $IsccCandidates = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
        )
        foreach ($Cand in $IsccCandidates) {
            if ($Cand -and (Test-Path $Cand)) {
                $IsccPath = $Cand
                break
            }
        }
    }
    if (-not $IsccPath) {
        throw "Inno Setup 6 (ISCC.exe) not found in PATH or standard install directories."
    }

    $ReleaseDir = Join-Path $RepoRoot "dist\release"
    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

    $IssScript = Join-Path $RepoRoot "installer\AntigravityControlCenter.iss"
    Write-Host "[Release] Compiling installer via $IsccPath..." -ForegroundColor Cyan
    & $IsccPath "/DAppVersion=$Version" $IssScript
    if ($LASTEXITCODE -ne 0) {
        throw "ISCC.exe failed with exit code $LASTEXITCODE"
    }

    $SetupName = "AntigravityControlCenter-Setup-$Version.exe"
    $SetupExe = Join-Path $ReleaseDir $SetupName
    if (-not (Test-Path $SetupExe)) {
        throw "Expected installer was not produced: $SetupExe"
    }

    # 6. Generate UTF-8 (no BOM) SHA256SUMS.txt
    $Hash = (Get-FileHash -Path $SetupExe -Algorithm SHA256).Hash.ToLowerInvariant()
    $SumsPath = Join-Path $ReleaseDir "SHA256SUMS.txt"
    $SumsContent = "$Hash  $SetupName`n"
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($SumsPath, $SumsContent, $Utf8NoBom)

    $SizeMB = [math]::Round((Get-Item $SetupExe).Length / 1MB, 2)
    Write-Host "[Release] Built installer: $SetupExe ($SizeMB MB)" -ForegroundColor Green
    Write-Host "[Release] Generated checksum: $SumsPath ($Hash)" -ForegroundColor Green

    # 7. Publish GitHub Release when -Publish is passed
    if ($Publish) {
        Write-Host "[Release] Publishing GitHub release $Tag..." -ForegroundColor Cyan
        gh release create $Tag $SetupExe $SumsPath --title "Antigravity Control Center $Tag" --generate-notes
        if ($LASTEXITCODE -ne 0) {
            throw "gh release create failed with exit code $LASTEXITCODE"
        }
        Write-Host "[Release] Published $Tag successfully!" -ForegroundColor Green
    }

    # 8. Install locally in-place and relaunch when -InstallLocal or -Publish (unless -SkipLocalInstall)
    if ($InstallLocal -or ($Publish -and -not $SkipLocalInstall)) {
        Write-Host "[Release] Updating local installed Antigravity Control Center..." -ForegroundColor Cyan
        Stop-InstalledApp

        $InstallerArgs = @(
            "/SILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
            "/FORCECLOSEAPPLICATIONS"
        )
        Write-Host "[Release] Running installer: $SetupExe" -ForegroundColor Cyan
        $Proc = Start-Process -FilePath $SetupExe -ArgumentList $InstallerArgs -Wait -PassThru
        if ($Proc.ExitCode -ne 0) {
            throw "Local installer exited with code $($Proc.ExitCode)"
        }

        Start-InstalledAppDetached
        Write-Host "[Release] Local installed app updated and relaunched successfully." -ForegroundColor Green
    }
}
finally {
    Pop-Location
}
