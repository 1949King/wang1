#!/usr/bin/env bash
# ============================================================
# 拾光剪影 · 提交前卡点（可入库版本，11 道）
#
# 本文件是**唯一真相源**；.git/hooks/pre-commit 只是一层 3 行 shim 调它。
# 为什么要把 hook 内容搬进仓库（2026-10-09）：
#   此前 9 道门禁的全部逻辑只存在于 .git/hooks/pre-commit —— 而 .git/ 不入库。
#   后果：① CI 没法复用（clone 下来根本没有这些门禁，所以 ci.yml 只能另写一套，
#   两边必然漂移）；② 换机器/重装即丢失；③ 没人能 review 门禁改了什么。
#   2026-10-09 同时补 ⑩ pyqtSignal 类型、⑪ 素材不出域 → 9 道变 11 道。
#
# 用法：
#   bash scripts/precommit_gates.sh          # 增量模式（= git hook，只看暂存文件）
#   bash scripts/precommit_gates.sh --all    # 全量模式（= CI，扫整个仓库）
#
# 两种模式的区别只在「看暂存还是看全部」，**判定标准完全一致**：
#   * 增量模式：只对本次 `git diff --cached` 里的文件判定（快，适合每次提交）
#   * 全量模式：对所有受控文件判定（慢，适合 CI / 合并前）
# 这样既保住了「增量严格」的哲学，又让 CI 能复用它做全量把关。
# ============================================================
set -u
cd "$(git rev-parse --show-toplevel)" || exit 1

ALL_MODE=0
[ "${1:-}" = "--all" ] && ALL_MODE=1
[ "${SHIGUANG_GATE_ALL:-0}" = "1" ] && ALL_MODE=1

PY=".venv312/Scripts/python.exe"
export PYTHONIOENCODING=utf-8
fail=0

# 解释器回退：本机 ruff 装在 C:/Python314；CI（ubuntu/windows runner）没有这个路径，
# 回落 `python -m ruff`（需 pip install ruff）。找不到就让 ① 自己报错，不静默跳过。
if [ -x "C:/Python314/python.exe" ]; then
    RUFF="C:/Python314/python.exe -m ruff"
elif command -v ruff >/dev/null 2>&1; then
    RUFF="ruff"
else
    RUFF="python -m ruff"
fi

if [ ! -f "$PY" ]; then
    # CI 上 venv 不叫 .venv312，回落当前 python
    PY="python"
fi

if [ "$ALL_MODE" = "1" ]; then
    echo "═══ 全量模式（CI / 合并前）——判定标准与增量模式完全一致 ═══"
fi

echo "── ① ruff 存量棘轮（逐文件：新文件必须 0 违规，已有文件只减不增）"
# 2026-10-07 换实现。原实现是「对暂存文件整体 ruff check --no-fix」，其意图
# （增量严格）没错，但整文件判定踩到结构性缺陷：白名单下 167 个文件带 1016 处
# **历史**违规（editor_module.py 50 · modules.py 76 · editor_effects_mixin.py 55 …），
# 而这些文件最后一次提交多在 09-21/22，**早于本 hook 诞生（09-26）**，
# 从未被扫过 ⇒ 任何对它们的正当改动都会被无关存量债拦死，
# 等于「冻结区的 editor_module.py 永远无法提交」。
# 现按 stability_gate 的既有范式改为**逐文件基线棘轮**（基线见
# docs/knowledge/ruff_gate_baseline.json）。门禁没有放松：新文件 >0、
# 或已有文件超过其基线，一律 fail=1。逐文件（而非全局计数）是为防
# 「A 修 3 处、B 加 3 处」此消彼长。
# 体检/重设基线：python scripts/ruff_gate.py --all | --report | --update [--force]
export SHIGUANG_RUFF="$RUFF"
if [ "$ALL_MODE" = "1" ]; then
    "$PY" scripts/ruff_gate.py --all || fail=1
else
    # 暂存清单由 **bash** 算好传给 python（2026-10-09）：
    # 受限/沙箱环境下 python 起 git 会被 CreateProcess 拒绝（WinError 5，
    # git 是 MSYS2 程序），而 bash 起 git 正常。不这样绕，hook 就会
    # 「读暂存区失败 → 回落全量 → 撞上工作区里别人的未跟踪文件 → 假红」，
    # 正当提交被无辜拦下。详见 ruff_gate.py::_staged_files()。
    SHIGUANG_STAGED_FILES="$(git diff --cached --name-only --diff-filter=ACM | tr '\n' ':')"
    export SHIGUANG_STAGED_FILES
    "$PY" scripts/ruff_gate.py || fail=1
    unset SHIGUANG_STAGED_FILES
fi
unset SHIGUANG_RUFF

if [ "$ALL_MODE" = "1" ]; then
    STAGED_PY=$(git ls-files -- 'app/modules/lego/*.py' 'app/core/*.py' 'ai_tools/*.py' \
        | grep -E '^(app/modules/lego|app/core|ai_tools)/' || true)
else
    STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM -- '*.py' \
        | grep -E '^(app/modules/lego|app/core|ai_tools)/' || true)
fi
if [ -n "$STAGED_PY" ]; then
    # format 只警告不拦截：存量文件风格未统一，强卡会逼每次提交
    # 都 reformat 整个文件造成巨型 diff；待 P2 仓库卫生阶段统一后再收紧。
    echo "── ② ruff format --check（仅警告）"
    echo "$STAGED_PY" | xargs "$RUFF" format --check 2>/dev/null || \
        echo "   ⚠️ 格式与 ruff-format 有差异（不阻断，建议新文件先格式化）"
else
    echo "   （无可检查的受控 .py 文件，跳过格式检查）"
fi

echo "── ③ 冻结区守护（85 锁点哈希）"
"$PY" scripts/frozen_zone_guard.py || fail=1

echo "── ④ 稳定性门禁（存量棘轮，只减不增）"
"$PY" scripts/stability_gate.py || fail=1

echo "── ⑤ 粘合层契约（跨线字段等价性）"
"$PY" _verify/check_glue_contract.py || fail=1

echo "── ⑥a 架构守护（分层纪律）"
"$PY" scripts/arch_guard.py --scan app || fail=1

echo "── ⑥b 双库一致性（防复漂，基线 分叉0/缺失7）"
"$PY" _verify/check_canvas_dual_repo.py || fail=1

echo "── ⑦ 前端三卡点（tsc 类型棘轮 + vitest 单测 + 质量棘轮）"
# 整改方案 P1-② 接线：_run_tsc.cjs / _run_vitest.cjs 已有但未挂载，
# 画布改动此前只有 ⑥b 一道卡点（现行技术文档 §839）。
# 增量模式仅暂存了画布文件时触发（与 ① 的增量哲学一致，不拖慢纯 Python 提交）；
# 全量模式无条件跑。副库 libtv 是真源副本，检查只对真源 shiguang-canvas 跑。
# tsc 基线 37 个错误全部位于 stage3d-core 冻结区 2 文件（Stage3D.tsx /
# riggedHumanoid.ts），清零需解冻 ⇒ 先做计数棘轮「只减不增」，解冻后下调基线。
if [ "$ALL_MODE" = "1" ]; then
    HAVE_CANVAS=1
else
    STAGED_CANVAS=$(git diff --cached --name-only --diff-filter=ACM -- \
        'vendor/shiguang-canvas/' 'vendor/AI-Canvas-tauri/src/libtv/' || true)
    [ -n "$STAGED_CANVAS" ] && HAVE_CANVAS=1 || HAVE_CANVAS=0
fi
if [ "$HAVE_CANVAS" = "0" ]; then
    echo "   （无暂存的画布文件，跳过）"
elif ! command -v node >/dev/null 2>&1; then
    echo "   ⚠️ 未找到 node，跳过前端卡点（不阻断，请尽快恢复 node 环境）"
elif [ ! -f vendor/shiguang-canvas/node_modules/vitest/vitest.mjs ]; then
    # CI 的 guards job 未装 npm 依赖；画布三卡点由 frontend-tests job 覆盖。
    # 这里显式跳过并说明，避免把「环境缺失」误报成「门禁失败」。
    echo "   ⚠️ 画布 node_modules 未安装，跳过前端三卡点"
    echo "      （CI 上由 frontend-tests job 覆盖 tsc + vitest + 质量棘轮）"
else
    # ⑦a tsc 类型检查（棘轮：错误数 ≤ 37 只减不增）
    TSC_OUT=$(cd vendor/shiguang-canvas && node node_modules/typescript/bin/tsc \
        --noEmit --pretty false 2>&1)
    TSC_N=$(printf '%s\n' "$TSC_OUT" | grep -c "error TS" || true)
    TSC_BASELINE=37
    if [ "$TSC_N" -gt "$TSC_BASELINE" ]; then
        echo "   ✗ tsc 错误 $TSC_N 个 > 基线 $TSC_BASELINE（新增 $((TSC_N - TSC_BASELINE)) 个）"
        printf '%s\n' "$TSC_OUT" | grep "error TS" | head -10
        fail=1
    else
        echo "   ✓ tsc 错误 $TSC_N 个 ≤ 基线 $TSC_BASELINE（棘轮只减不增）"
    fi
    # ⑦b vitest 单测（失败即拦截）
    # --pool=threads：默认 forks pool 会把 SSR 编译结果写临时目录供 worker
    # 读取，被 WorkBuddy fs-shim 拦截（EPERM）造成假失败；threads 走内存
    # 通道不写盘，沙箱安全（2026-09-26 实测定位）。
    VT_OUT=$(cd vendor/shiguang-canvas && node node_modules/vitest/vitest.mjs \
        run --reporter=dot --pool=threads 2>&1)
    VT_RC=$?
    if [ "$VT_RC" -ne 0 ]; then
        echo "   ✗ vitest 单测失败（尾部输出）："
        printf '%s\n' "$VT_OUT" | tail -15
        fail=1
    else
        VT_N=$(printf '%s\n' "$VT_OUT" | sed 's/\x1b\[[0-9;]*m//g' \
            | grep -oE 'Tests +[0-9]+ passed' | grep -oE '[0-9]+' | head -1)
        echo "   ✓ vitest 单测通过（${VT_N:-?} 个）"
    fi
    # ⑦c 前端质量棘轮（check_canvas_frontend_quality.mjs）
    # 报告型脚本改造为卡点：dupNames ≤8 / fnOver300 ≤10 / cycloOver60 ≤5
    # 只减不增。基线 8 组同名已人工定性＝启发式误报（多行箭头回调/局部
    # 同名，非模块级静默覆盖），新增同名即拦。
    # 2026-10-07 fnOver300 9→10：新增档来自 stage3dPoseLibrary.ts，该文件里
    # defaultPose() 本体只有 3 行，但其后紧跟 541 行 POSE_PRESETS **数据表**，
    # 而本脚本的 len 是「到下一个函数起点」的近似 ⇒ 把数据表算进了前一个函数
    # 的跨度（同因导致 CanvasShell/pathOf 显示 2908/1498 行）。逐文件移除实测
    # 该文件即回落 9，确认归因。属启发式误报，按 dupNames 先例人工定性记录。
    # 回落路径：若日后把 POSE_PRESETS 单独建数据模块，须同步
    # _verify/check_stage3d_pose_dof.mjs（它按源文本解析该文件），届时可改回 9。
    Q_JSON=$(node _verify/check_canvas_frontend_quality.mjs --json 2>/dev/null)
    if [ -z "$Q_JSON" ]; then
        echo "   ✗ 前端质量扫描执行失败"
        fail=1
    else
        Q_VERDICT=$(printf '%s' "$Q_JSON" | node -e "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{const j=JSON.parse(s).summary;const base={dupNames:8,fnOver300:10,cycloOver60:5};const bad=Object.entries(base).filter(([k,v])=>(j[k]||0)>v);if(bad.length){console.log('FAIL '+bad.map(([k,v])=>k+'='+j[k]+'>'+v).join(' '))}else{console.log('OK dupNames='+j.dupNames+'/8 fnOver300='+j.fnOver300+'/10 cycloOver60='+j.cycloOver60+'/5')}});")
        case "$Q_VERDICT" in
            OK*) echo "   ✓ 质量棘轮 ${Q_VERDICT#OK }" ;;
            *)   echo "   ✗ 质量棘轮新增超限：${Q_VERDICT#FAIL }"; fail=1 ;;
        esac
    fi
fi

echo "── ⑧ 单文件规模守卫（存量冻结，只减不增）"
# 2026-09-27 补：此前该守卫不在 hook 里，导致「加代码把文件撑过 2000 行」
# 无人拦（canvas_server +41 行越界即是一例）。守卫本身只维护基线，成本极低。
"$PY" _verify/check_file_size.py || fail=1

echo "── ⑨ 路由 mixin 属性可解析（cs.* 防静默失效）"
# 2026-09-27 补：A4 迁出端点后 ruff --fix 会删「看似未用」的 import，
# 让 mixin 的 cs.xxx 变 AttributeError、端点静默失效。纯静态、毫秒级。
"$PY" _verify/check_canvas_route_attrs.py || fail=1

echo "── ⑩ pyqtSignal 参数类型（防 typing 泛型别名致整模块 import 崩）"
# 2026-10-09 补（实测事故）：app/core/ai_interpolation.py:249 写的是
#   pyqtSignal(float, List[np.ndarray])
# pyqtSignal 不接受 _GenericAlias ⇒ 类体执行期抛 TypeError ⇒ **整个模块
# import 失败**。连锁：preview_manager 那句 import 无 try/except（开补帧即崩），
# deformity_repair_skill 被 try/except 吞掉 ⇒ Agent 补帧能力静默失效。
# 同批还查出 highlight_preview.py 3 处同型缺陷。ruff/tsc 都看不见（语法合法），
# 只有 AST 能提前拦。纯静态、毫秒级。
"$PY" _verify/check_qt_signal_types.py || fail=1

echo "── ⑪ 素材不出域开关（SHIGUANG_NO_EGRESS 硬约束）"
# 2026-10-09 补：provider_caps.resolve_order() 默认「优先云端」，此前没有任何
# 开关能表达「这一单不许出域」。纯逻辑断言，毫秒级。
"$PY" _verify/check_provider_egress.py || fail=1

if [ "$fail" -ne 0 ]; then
    echo ""
    echo "✗ 提交前卡点未通过，请修复后重试（紧急跳过：git commit --no-verify）"
    exit 1
fi
echo "✓ 提交前卡点全部通过（11 道）"
exit 0
