__version__ = "4.46.15"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 15,
    "codename": "统一推理引擎 M2 · 后端收编 + SVD 引擎归属诚实修正",
    "release_date": "2026-10-24",
    "description": (
        "V4.46.15：统一引擎路线 M2（后端收编）。接线过程中发现并修正一处我自己在\n"
        "V4.46.11 引入的登记错误——教训入库，写在这里免得后人重查。\n"
        "\n【① 接线：execution_planner 改读模型族注册表】\n"
        "model_family 新增 BACKEND_TO_ENGINE（模块 id → 引擎 id）与 preferred_engines()\n"
        "（族 → 引擎优先级序，backend_registry 命名空间）；planner 的「无实测证据保守\n"
        "默认」从写死 diffsynth→diffusers 改为查注册表（svd 族 → diffusers 唯一序）。\n"
        "注册表不可用/族未登记 ⇒ 退回旧默认，行为与改动前逐键一致（兜底不变）。\n"
        "is_fallback 语义同步修正：主选基准 = 注册表序首个可用，不再写死「!= diffsynth\n"
        "即备选」——SVD 选 diffusers 是唯一正解，旧语义会把它误标成降级。\n"
        "\n【② 事实修正：SVD 的引擎归属是 diffusers，不是 diffsynth】\n"
        "video_gen.py:419 实测 `from diffusers import DiffusionPipeline`；③ local_video_infer\n"
        "的 _infer_svd 同样走 diffusers ⇒ 两条 SVD 实现 import 的都是 diffusers。\n"
        "V4.46.11 我修「svd 漏登记误杀视频路径」时，把 svd 登记到了 diffsynth 名下——\n"
        "当时只恢复了路由，归属不实（假登记比漏登记更隐蔽：规划器会选一个跑不通的栈）。\n"
        "本刀按真实依赖修正：backend_registry 的 diffusers 挂 svd、diffsynth 撤 svd；\n"
        "回归锁 test_svd_arch_is_routable 断言改为诚实事实（diffusers 在、diffsynth 不在、\n"
        "只有 diffsynth 的机器 svd 判不可用）；设计稿 §1.1 同步修正并记教训。\n"
        "\n【③ 测试】\n"
        "test_model_family.py +2 例（preferred_engines 映射全族断言；planner 视频探测\n"
        "engine=diffusers 且 is_fallback=False 且 reason 可见默认序来源；图像族对照回归）。\n"
        "接线验证时发现并修掉测试自身一处键名错误（_engine_probe 返回 reason 字符串\n"
        "而非 reasons 列表）——失败先读详情再改，不猜。\n"
        "\n【验证】全量 pytest 1969 passed；run_all_checks 109 项全绿；frozen_zone_guard\n"
        "106 锁；ruff 棘轮零新增；stability gate 251/251 无新增。\n"
        "\n【上一版 V4.46.14『统一推理引擎 M1 · 模型族注册表』见 docs/CHANGELOG.md。】"
    ),
}
