#!/usr/bin/env bash
# ============================================================
# 拾光剪影 · 一任务一分支 + 自动回滚（task_branch.sh）
#
# 背景（2026-10-09）：本仓库此前**长期在 main 上直提**，没有分支模型、
# 没有回滚锚点。对「让 Agent 长时间自主改代码」这个用法来说这是最危险的一条：
# 一旦跑坏，没有「一键回到上一个绿灯」。
#
# 核心思路（对齐第三方分析里那句「防的不是模型笨，防的是模型会犯错」）：
#   ① 每个任务开一条独立分支  ⇒ 爆炸半径限制在一个任务内
#   ② 合并的唯一判据是 check_all.sh 全绿（不是「看起来对了」）
#   ③ 每次绿灯打 green/<任务名>-<日期> tag ⇒ 回滚锚点
#   ④ 回滚前先备份当前 HEAD ⇒ 回滚本身也可回滚
#
# 用法：
#   bash scripts/task_branch.sh start   <任务名>     # 从 clean 的 main 开任务分支
#   bash scripts/task_branch.sh status               # 当前分支 / 绿灯 tag / 落后情况
#   bash scripts/task_branch.sh done    <任务名>     # 体检→打绿灯→合并回 main
#   bash scripts/task_branch.sh done    <任务名> --keep   # 只打绿灯，不合并
#   bash scripts/task_branch.sh abort   <任务名>     # 丢弃任务分支（需 --yes）
#   bash scripts/task_branch.sh rollback             # 回滚到最近绿灯 tag
#   bash scripts/task_branch.sh rollback <tag>       # 回滚到指定 tag
#   bash scripts/task_branch.sh rollback --list      # 列出可用绿灯 tag
#
# 分支命名：task/<任务名>（任务名里的非法字符会被规整成 `-`）
# 绿灯命名：green/<任务名>-YYYY-MM-DD（同日同名会加 -2 / -3…）
# 回滚备份：backup/pre-rollback-YYYYMMDD-HHMMSS
# ============================================================
set -u

cd "$(git rev-parse --show-toplevel)" || exit 1

GATES="scripts/check_all.sh"
PY=".venv312/Scripts/python.exe"
[ -f "$PY" ] || PY="python"

# ── 工具函数 ──────────────────────────────────────────────
c_red()   { printf '\033[31m%s\033[0m\n' "$*"; }
c_grn()   { printf '\033[32m%s\033[0m\n' "$*"; }
c_ylw()   { printf '\033[33m%s\033[0m\n' "$*"; }
die()     { c_red "✗ $*"; exit 1; }

sanitize() {
    # 任务名规整：中文保留（git 支持），只去掉 git ref 非法字符与空白
    printf '%s' "$1" | tr ' ' '-' | tr -d '~^:?*[\\' | sed 's#\.\.*#.#g; s#/$##; s#^[-.]#_#'
}

current_branch() { git rev-parse --abbrev-ref HEAD; }

require_main_free() {
    # 允许有未跟踪文件；但有已跟踪文件的改动就不许开新任务
    if ! git diff --quiet || ! git diff --cached --quiet; then
        c_red "✗ 工作区有未提交的**已跟踪文件**改动，先提交或 stash 再开任务："
        git status --short --untracked-files=no | head -20
        die "工作区不干净"
    fi
}

latest_green() {
    git tag -l 'green/*' --sort=-creatordate | head -1
}

# ── 子命令 ────────────────────────────────────────────────
cmd_start() {
    local raw="$1" name base
    name="$(sanitize "$raw")"
    [ -n "$name" ] || die "任务名不能为空"
    base="$(current_branch)"
    echo "── 开任务分支：当前在 $base，检查工作区…"
    require_main_free
    if git show-ref --verify --quiet "refs/heads/task/$name"; then
        c_ylw "⚠️ 分支 task/$name 已存在，直接切过去（不重建）"
        git switch "task/$name" || die "切换失败"
    else
        git switch -c "task/$name" || die "创建失败"
    fi
    git branch --set-upstream-to="$base" "task/$name" 2>/dev/null || true
    c_grn "✓ 已进入 task/$name（基线 $base @ $(git rev-parse --short HEAD)）"
    echo "   做完后：bash scripts/task_branch.sh done $raw"
}

cmd_status() {
    local br tag
    br="$(current_branch)"
    tag="$(latest_green)"
    echo "── 当前分支：$br"
    echo "   最近绿灯：${tag:-（无）}"
    if [ -n "$tag" ]; then
        echo "   自最近绿灯以来：$(git rev-list --count "$tag"..HEAD 2>/dev/null || echo '?') 个提交"
    fi
    echo "   本地分支："
    git for-each-ref --format='     %(refname:short)  %(committerdate:short)  %(subject)' refs/heads/task refs/heads/main 2>/dev/null
    echo "   绿灯 tag（最近 10）："
    git tag -l 'green/*' --sort=-creatordate | head -10 | sed 's/^/     /'
    echo "   工作区："
    git status --short | head -15 | sed 's/^/     /'
    local n; n=$(git status --porcelain --untracked-files=all | wc -l | tr -d ' ')
    echo "     （共 $n 项变动，含未跟踪）"
}

cmd_done() {
    local raw="$1" keep="${2:-}" name br
    name="$(sanitize "$raw")"
    br="$(current_branch)"
    [ "$br" = "task/$name" ] || c_ylw "⚠️ 当前分支是 $br（不是 task/$name），继续用当前分支"
    [ "$br" = "main" ] && die "不允许在 main 上执行 done（没有可合并的任务分支）"

    echo "════════════════════════════════════════════════════════════"
    echo " 合并前体检（唯一判据）—— 这一步不过就不许合并"
    echo "════════════════════════════════════════════════════════════"
    if ! bash "$GATES"; then
        c_red "✗ 体检未通过，**拒绝合并**。你仍在 $br 上，修好后再跑 done。"
        exit 1
    fi

    # 体检可能改动了工作区（如 vitest 缓存），确认干净以便打 tag
    if ! git diff --quiet || ! git diff --cached --quiet; then
        c_ylw "⚠️ 体检后有已跟踪文件改动，先提交它们（commit 后才打绿灯）"
        git status --short --untracked-files=no | head -20
        exit 1
    fi

    # 打绿灯 tag（同名同日递增加后缀）
    local base_tag; base_tag="green/$name-$(date +%Y-%m-%d)"
    local tag="$base_tag" n=1
    while git rev-parse -q --verify "refs/tags/$tag" >/dev/null; do
        n=$((n + 1)); tag="$base_tag-$n"
    done
    git tag -a "$tag" -m "green: $name（check_all.sh 全绿 @ $(git rev-parse --short HEAD)）" \
        || die "打 tag 失败"
    c_grn "✓ 绿灯 tag：$tag"

    if [ "$keep" = "--keep" ]; then
        c_ylw "（--keep：不合并，分支 $br 保留）"
        return 0
    fi

    local main_branch="main"
    git show-ref --verify --quiet refs/heads/main || main_branch="master"
    echo "── 合并回 $main_branch（--no-ff，保留任务边界）"
    git switch "$main_branch" || die "切回 $main_branch 失败"
    if git merge --no-ff "$br" -m "merge: $name（绿灯 $tag）"; then
        c_grn "✓ 已合并到 $main_branch"
        echo "   如需清理任务分支：git branch -d $br"
    else
        c_red "✗ 合并冲突 —— 已停在 $main_branch 的合并过程中。"
        echo "   解决后 git commit；放弃用 git merge --abort，然后 git switch $br"
        exit 1
    fi
}

cmd_abort() {
    local raw="$1" yes="${2:-}" name br
    name="$(sanitize "$raw")"
    br="$(current_branch)"
    if [ "$yes" != "--yes" ]; then
        c_ylw "将删除分支 task/$name（未合并的改动会永久丢失）。确认请加 --yes。"
        echo "  当前分支：$br ｜ 该分支比 main 多 $(git rev-list --count main.."task/$name" 2>/dev/null || echo '?') 个提交"
        exit 2
    fi
    [ "$br" = "task/$name" ] && git switch main
    # 先打一个 backup tag，别让「丢弃」变成不可逆
    git tag -a "backup/aborted-$name-$(date +%Y%m%d-%H%M%S)" "task/$name" \
        -m "abort 前的自动备份（task/$name）" 2>/dev/null || true
    git branch -D "task/$name" && c_grn "✓ 已删除 task/$name（备份 tag 见 backup/aborted-*）"
}

cmd_rollback() {
    local tag="$1"
    if [ "$tag" = "--list" ] || [ "$tag" = "-l" ]; then
        echo "可用绿灯 tag（新→旧）："
        git tag -l 'green/*' --sort=-creatordate | head -30 | sed 's/^/  /'
        return 0
    fi
    [ -n "$tag" ] || tag="$(latest_green)"
    [ -n "$tag" ] || die "没有任何 green/* tag，无可回滚目标"
    git rev-parse -q --verify "refs/tags/$tag" >/dev/null || die "tag 不存在：$tag"

    echo "════════════════════════════════════════════════════════════"
    c_ylw " 回滚操作 —— 目标 tag：$tag"
    echo " 这将把 main 指针移到该 tag 所指向的提交，并同步工作区文件。"
    echo " 你当前 HEAD：$(git rev-parse --short HEAD)（$(current_branch)）"
    echo "────────────────────────────────────────────────────────────"
    git --no-pager log --oneline -1 "$tag"
    echo "════════════════════════════════════════════════════════════"

    # ① 先把当前 HEAD 备份成 tag（回滚也可回滚）
    local bk="backup/pre-rollback-$(date +%Y%m%d-%H%M%S)"
    git tag -a "$bk" -m "回滚到 $tag 之前的状态" HEAD || die "备份 tag 失败"
    c_grn "✓ 已备份当前状态：$bk"

    # ② 用 -C 重建 main 到目标（工作区随之更新）
    #    注意：这里用 checkout 到 tag 再重建 main，避免 reset --hard 丢未跟踪文件。
    git switch -C main "$tag" || die "重建 main 失败"
    c_grn "✓ 已回滚：main → $tag（$(git rev-parse --short HEAD)）"
    echo "   撤销本次回滚：git switch -C main $bk"
    echo "   工作区状态（未跟踪文件不会被回滚）："
    git status --short | head -10 | sed 's/^/     /'
}

# ── 分发 ──────────────────────────────────────────────────
case "${1:-}" in
    start)    [ $# -ge 2 ] || die "用法：task_branch.sh start <任务名>"; cmd_start "$2" ;;
    status)   cmd_status ;;
    done)     [ $# -ge 2 ] || die "用法：task_branch.sh done <任务名> [--keep]"; cmd_done "$2" "${3:-}" ;;
    abort)    [ $# -ge 2 ] || die "用法：task_branch.sh abort <任务名> --yes"; cmd_abort "$2" "${3:-}" ;;
    rollback) cmd_rollback "${2:-}" ;;
    -h|--help|"")
        sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
        ;;
    *) die "未知子命令：$1（用 --help 看用法）" ;;
esac
