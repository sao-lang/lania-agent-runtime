<#
.SYNOPSIS
    从 lania-shared-skills 同步技能规则到本项目
.DESCRIPTION
    共享目录是规范源（source of truth）。

    三种模式：
      默认     — 从共享目录复制真实文件到项目（覆盖已有文件）
      -ToReal  — 移除 junction，复制真实文件（供 pre-commit 使用）
      -ToJunction — 移除真实文件，创建 junction（供 post-commit 使用）
.PARAMETER ToReal
    将 junction 替换为真实文件副本
.PARAMETER ToJunction
    将真实文件替换为 junction 链接
#>

param(
    [switch]$ToReal,
    [switch]$ToJunction
)

$SharedRoot = "E:\vsc-workspace\lania-shared-skills"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$TargetDir = Join-Path $ProjectRoot ".github\skills"

$Skills = @("ai-coding-rules", "grill-me", "code-review", "simplify")

# ── 辅助函数 ──

function Test-IsJunction($Path) {
    if (-not (Test-Path $Path)) { return $false }
    $fsInfo = Get-Item $Path -Force
    return $fsInfo.Attributes -band [System.IO.FileAttributes]::ReparsePoint
}

function Remove-SkipWorktree($ProjectRoot) {
    $files = git -C $ProjectRoot ls-files .github/skills/ 2>$null
    if ($files) {
        $files | ForEach-Object { git -C $ProjectRoot update-index --no-skip-worktree $_ 2>$null }
    }
    # 也处理 copilot-instructions.md
    $md = git -C $ProjectRoot ls-files .github/copilot-instructions.md 2>$null
    if ($md) { git -C $ProjectRoot update-index --no-skip-worktree $md 2>$null }
}

function Set-SkipWorktree($ProjectRoot) {
    $files = git -C $ProjectRoot ls-files .github/skills/ 2>$null
    if ($files) {
        $files | ForEach-Object { git -C $ProjectRoot update-index --skip-worktree $_ 2>$null }
    }
    # 也处理 copilot-instructions.md
    $md = git -C $ProjectRoot ls-files .github/copilot-instructions.md 2>$null
    if ($md) { git -C $ProjectRoot update-index --skip-worktree $md 2>$null }
}

function Copy-SharedToProject {
    Write-Host "🔄 复制真实文件到项目 ..." -ForegroundColor Cyan
    $Skills | ForEach-Object {
        $src = Join-Path $SharedRoot $_
        $dst = Join-Path $TargetDir $_
        if (Test-Path $src) {
            if (Test-Path $dst) {
                Remove-Item -Path $dst -Recurse -Force -ErrorAction SilentlyContinue
            }
            Copy-Item -Path $src -Destination $dst -Recurse -Force
            Write-Host "   ✅ $_" -ForegroundColor Green
        }
    }
    # 复制 copilot-instructions.md
    $mdSrc = Join-Path $SharedRoot "copilot-instructions.md"
    $mdDst = Join-Path $ProjectRoot ".github\copilot-instructions.md"
    if (Test-Path $mdSrc) {
        Copy-Item -Path $mdSrc -Destination $mdDst -Force
        Write-Host "   ✅ copilot-instructions.md" -ForegroundColor Green
    }
}

# ── 主逻辑 ──

if (-not (Test-Path $SharedRoot)) {
    Write-Warning "⚠️ 共享技能目录不存在：$SharedRoot，跳过同步"
    exit 0
}

if ($ToReal) {
    # 移除 junction → 复制真实文件 → 清除 skip-worktree
    Write-Host "🔁 切换为真实文件模式（供 Git 提交）..." -ForegroundColor Yellow
    $Skills | ForEach-Object {
        $p = Join-Path $TargetDir $_
        if ((Test-Path $p) -and (Test-IsJunction $p)) {
            cmd /c "rmdir /s /q $p" 2>$null
            Write-Host "   🗑️  移除 junction: $_" -ForegroundColor Gray
        }
    }
    # 处理 copilot-instructions.md symlink
    $mdLink = Join-Path $ProjectRoot ".github\copilot-instructions.md"
    if (Test-Path $mdLink) {
        $item = Get-Item $mdLink -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            Remove-Item $mdLink -Force
            Write-Host "   🗑️  移除 copilot-instructions.md symlink" -ForegroundColor Gray
        }
    }
    Copy-SharedToProject
    Remove-SkipWorktree $ProjectRoot
    Write-Host "✅ 已切换为真实文件，Git 可感知改动。提交完成后请运行 sync-skills.ps1 -ToJunction 恢复。" -ForegroundColor Green
}
elseif ($ToJunction) {
    # 移除真实文件 → 创建 junction/symlink → 设置 skip-worktree
    Write-Host "🔁 切换为 junction 模式（实时同步）..." -ForegroundColor Yellow
    $Skills | ForEach-Object {
        $p = Join-Path $TargetDir $_
        if (Test-Path $p) {
            if (Test-IsJunction $p) {
                Write-Host "   ⏭️  已是 junction: $_" -ForegroundColor Gray
                return
            }
            Remove-Item -Path $p -Recurse -Force -ErrorAction SilentlyContinue
        }
        $src = Join-Path $SharedRoot $_
        cmd /c "mklink /J `"$p`" `"$src`"" 2>$null
        Write-Host "   🔗 创建 junction: $_" -ForegroundColor Gray
    }
    # 处理 copilot-instructions.md symlink
    $mdLink = Join-Path $ProjectRoot ".github\copilot-instructions.md"
    $mdSrc = Join-Path $SharedRoot "copilot-instructions.md"
    if (Test-Path $mdLink) {
        $item = Get-Item $mdLink -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            Write-Host "   ⏭️  已是 symlink: copilot-instructions.md" -ForegroundColor Gray
        } else {
            Remove-Item $mdLink -Force
            cmd /c "mklink `"$mdLink`" `"$mdSrc`"" 2>$null
            Write-Host "   🔗 创建 symlink: copilot-instructions.md" -ForegroundColor Gray
        }
    } else {
        cmd /c "mklink `"$mdLink`" `"$mdSrc`"" 2>$null
        Write-Host "   🔗 创建 symlink: copilot-instructions.md" -ForegroundColor Gray
    }
    Set-SkipWorktree $ProjectRoot
    Write-Host "✅ 已切换为 junction，实时同步共享目录更改，Git 已忽略该目录。" -ForegroundColor Green
}
else {
    # 默认：真实文件 → 真实文件（覆盖同步）
    if (-not (Test-Path $TargetDir)) {
        New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    }
    Copy-SharedToProject
    Write-Host "✅ 同步完成" -ForegroundColor Green
}
