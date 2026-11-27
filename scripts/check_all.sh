#!/usr/bin/env bash
# ============================================================
# 拾光剪影 · 全量体检单一入口（check_all.sh）
#
# 一条命令跑完全部质量关卡，任何一步失败即非零退出。
# 这是**本地 CI 等价物**：.github/workflows/ci.yml 的每一步都对应本文件中的
# 一个 STEP，两边必须保持一致（改一边必须改另一边，见 §CI 同步纪律）。
#
# 用法：
#   bash scripts/check_all.sh            # 全量（默认，约 8-11 分钟）
#   bash scripts/check_all.sh --fast     # 快速（只跑静态门禁 + 验证套件，约 1-2 分钟）
#   bash scripts/check_all.sh --no-cov   # 全量但不跑覆盖率棘轮
#   bash scripts/check_all.sh --list     # 只列出会跑哪些步骤
#
# 退出码：0=全绿；1=有步骤失败；2=用法错误；3=环境不满足（缺 venv/node）
# ------------------------------------------------------------
# 为什么需要这个文件（2026-10-09）：
#   此前四套入口互相不知道对方存在 —— 9 道 pre-commit 门禁只在你 git commit
#   时触发；877 个 pytest 用例要自己敲；235 个 vitest 要 cd 进画布；72 项
#   run_all_checks 又在另一个地方。结果是「没人会全跑」，覆盖率掉到 21%。
#   本文件把它们串成一条链，并且是 task_branch.sh 合并前的唯一判据。
# ============================================================
set -u

cd "$(git rev-parse --show-toplevel)" || exit 1

PY=".venv312/Scripts/python.exe"
COV_JSON=".workbuddy/tmp/coverage.json"

MODE="full"
NO_COV=0
for arg in "$@"; do
    case "$arg" in
        --fast)   MODE="fast" ;;
        --no-cov) NO_COV=1 ;;
        --list)   MODE="list" ;;
        -h|--help)
            sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "未知参数：$arg（用 --help 看用法）" >&2; exit 2 ;;
    esac
done

# ── 步骤定义： 标识 | 人类可读名 | 命令 ────────────────────
STEP_IDS=(GATES PYTEST COVRATCH VITEST ALLCHECKS)
STEP_NAMES=(
    "① 提交前 11 道门禁（ruff/format/冻结区/稳定性/契约/架构/双库/前端三卡点/规模/路由/Signal/不出域）"
    "② Python 单测（pytest 全量 + 覆盖率采样）"
    "③ 覆盖率棘轮（只增不减）"
    "④ 画布前端单测（vitest）"
    "⑤ 验证套件（run_all_checks，含真起 bridge 的 e2e）"
)

step_cmd() {
    case "$1" in
        # 走仓库内的 scripts/precommit_gates.sh（可入库版本），不是 .git/hooks/——
        # 后者不入库、CI 拿不到。
        # 2026-10-09 定案：**体检入口一律传 --all（全量）**，不再按环境切增量。
        #   原设计「本地增量 / CI 全量」有两个硬伤：
        #   ① 体检是「同一份代码 → 同一结果」的可复现动作，而增量模式依赖 git 暂存区，
        #      同一份代码 staged 与否结果不同 —— 不可复现的体检没有意义；
        #   ② 本地增量 vs CI 全量 = 判定标准不一致，正是当初把门禁从 .git/ 搬进
        #      仓库要消除的问题（见 precommit_gates.sh 头部）。
        #   「提交时只查改动文件」的增量严格性由 git hook 自身保证（那时必有暂存文件）。
        GATES)     echo 'bash scripts/precommit_gates.sh --all' ;;
        PYTEST)    if [ "$NO_COV" = "1" ]; then
                       echo "QT_QPA_PLATFORM=offscreen \"$PY\" -m pytest -q"
                   else
                       echo "QT_QPA_PLATFORM=offscreen \"$PY\" -m pytest -q --cov=app --cov-report=term:skip-covered --cov-report=json:$COV_JSON"
                   fi ;;
        COVRATCH)  echo "\"$PY\" _verify/check_coverage.py --json $COV_JSON" ;;
        VITEST)    echo '( cd vendor/packages/canvas-core && node node_modules/vitest/vitest.mjs run --reporter=dot --pool=threads )' ;;
        ALLCHECKS) echo "\"$PY\" _verify/run_all_checks.py" ;;
    esac
}

if [ "$MODE" = "list" ]; then
    echo "check_all.sh 将按顺序执行："
    for i in "${!STEP_IDS[@]}"; do
        printf '  %s\n      $ %s\n' "${STEP_NAMES[$i]}" "$(step_cmd "${STEP_IDS[$i]}")"
    done
    echo
    echo "  快速模式（--fast）只跑：GATES, ALLCHECKS"
    exit 0
fi

if [ "$MODE" = "fast" ]; then
    RUN=(GATES ALLCHECKS)
else
    RUN=(GATES PYTEST COVRATCH VITEST ALLCHECKS)
    if [ "$NO_COV" = "1" ]; then
        RUN=(GATES PYTEST VITEST ALLCHECKS)
    fi
fi

# CI 环境（无 .venv312 / 有 GITHUB_ACTIONS）自动切全量门禁模式
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    export SHIGUANG_GATE_ALL=1
    echo "（检测到 GITHUB_ACTIONS=true → 门禁切全量模式 SHIGUANG_GATE_ALL=1）"
fi

# ── 环境自检（避免「跑错解释器」类假失败）──────────────────
echo "════════════════════════════════════════════════════════════"
echo " 拾光剪影 · 全量体检（模式：$MODE）"
echo "════════════════════════════════════════════════════════════"
echo "── 环境自检"
if [ ! -f "$PY" ]; then
    echo "   ✗ 找不到项目解释器 $PY"
    echo "     本仓库必须用 .venv312 跑校验：系统 Python 缺 psutil/pynvml/pypinyin，"
    echo "     会把「缺依赖」误报成功能回归（见 docs/现行技术文档.md）。"
    exit 3
fi
echo "   ✓ 解释器 $PY"
if ! command -v node >/dev/null 2>&1; then
    echo "   ⚠️ 未找到 node —— 画布 vitest 与前端卡点会被跳过（不算失败）"
else
    echo "   ✓ node $(node -v)"
fi
if [ ! -f vendor/packages/canvas-core/node_modules/vitest/vitest.mjs ]; then
    echo "   ⚠️ 画布 node_modules 缺失 —— vitest 步骤会失败（先在 vendor 运行 pnpm install）"
fi
echo

# ── 逐步执行 ──────────────────────────────────────────────
FAILED=()
declare -a DUR=()

run_step() {
    local id="$1" name="$2" cmd="$3"
    local t0 t1 rc
    echo "════════════════════════════════════════════════════════════"
    echo " $name"
    echo " \$ $cmd"
    echo "────────────────────────────────────────────────────────────"
    t0=$(date +%s)
    eval "$cmd"
    rc=$?
    t1=$(date +%s)
    DUR+=("$id:$((t1 - t0))s")
    if [ "$rc" -ne 0 ]; then
        echo ""
        echo " ✗ $id 失败（退出码 $rc）"
        FAILED+=("$id")
    else
        echo " ✓ $id 通过（$((t1 - t0))s）"
    fi
    echo
}

for id in "${RUN[@]}"; do
    # 取 STEP_NAMES 中对应下标的名称
    for i in "${!STEP_IDS[@]}"; do
        if [ "${STEP_IDS[$i]}" = "$id" ]; then
            run_step "$id" "${STEP_NAMES[$i]}" "$(step_cmd "$id")"
            break
        fi
    done
done

# ── 汇总 ──────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════════"
echo " 体检汇总"
echo "────────────────────────────────────────────────────────────"
for d in "${DUR[@]}"; do
    printf '   %-12s %s\n' "${d%%:*}" "${d##*:}"
done
echo "────────────────────────────────────────────────────────────"
if [ "${#FAILED[@]}" -eq 0 ]; then
    echo " ✓ 全量体检通过（共 ${#RUN[@]} 步）"
    exit 0
fi
echo " ✗ 失败步骤：${FAILED[*]}"
echo "   排查顺序：① 解释器对不对（必须 .venv312）② 是否撞上并发会话"
echo "             ③ 才是真回归。见技能 shiguang-guard-diagnostics。"
exit 1
