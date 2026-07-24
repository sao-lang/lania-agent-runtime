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

$Skills = @("ai-coding-rules", "debug-tools")

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
}

function Set-SkipWorktree($ProjectRoot) {
    $files = git -C $ProjectRoot ls-files .github/skills/ 2>$null
    if ($files) {
        $files | ForEach-Object { git -C $ProjectRoot update-index --skip-worktree $_ 2>$null }
    }
}

function Copy-SharedToProject {
    Write-Host "🔄 复制真实文件到项目 ..." -ForegroundColor Cyan
    @("ai-coding-rules", "debug-tools") | ForEach-Object {
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
}

# ── 主逻辑 ──

if (-not (Test-Path $SharedRoot)) {
    Write-Warning "⚠️ 共享技能目录不存在：$SharedRoot，跳过同步"
    exit 0
}

if ($ToReal) {
    # 移除 junction → 复制真实文件 → 清除 skip-worktree
    Write-Host "🔁 切换为真实文件模式（供 Git 提交）..." -ForegroundColor Yellow
    @("ai-coding-rules", "debug-tools") | ForEach-Object {
        $p = Join-Path $TargetDir $_
        if ((Test-Path $p) -and (Test-IsJunction $p)) {
            cmd /c "rmdir /s /q $p" 2>$null
            Write-Host "   🗑️  移除 junction: $_" -ForegroundColor Gray
        }
    }
    Copy-SharedToProject
    Remove-SkipWorktree $ProjectRoot
    Write-Host "✅ 已切换为真实文件，Git 可感知改动。提交完成后请运行 sync-skills.ps1 -ToJunction 恢复。" -ForegroundColor Green
}
elseif ($ToJunction) {
    # 移除真实文件 → 创建 junction → 设置 skip-worktree
    Write-Host "🔁 切换为 junction 模式（实时同步）..." -ForegroundColor Yellow
    @("ai-coding-rules", "debug-tools") | ForEach-Object {
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
