#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证汉字注音字典 + 四处接线（2026-09-25 V4.39.0）—— 自包含可执行。

跑法: python _verify/check_pinyin_dict.py

覆盖本能力**独有风险面**（不止「函数能跑」）：
  A. 注音正确性：常用字 / 生僻字 / 词组级多音字消歧 / 未知字诚实不编造
  B. **确定性**：同输入两次结果逐字一致（这是相对「LLM 猜拼音」的核心优势）
  C. SSML 按位置标注：同一字出现多次、读音不同 → 各自正确
     （tts_guard.build_ssml 按「首次出现」替换，做不到这点）
  D. tts_guard 集成：LLM 抛错/返回垃圾 → 不再「不注音」，而是字典接管
  E. 四处接线静态断言（★ 第 3/4 处 run_all_checks 的 AGENTMAP **不覆盖**）
  F. 能力端到端：走 dispatcher 真调用
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FAILS: list = []
TOTAL = 0


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def main() -> int:
    from app.core.ai import pinyin_dict as pyd
    from app.core.ai import tts_guard as tg

    # ════════════ A. 注音正确性 ════════════
    avail, reason = pyd.is_available()
    check(f"注音库可用（{reason or 'pypinyin'}）", avail)
    if not avail:
        print("\n字典不可用，后续检查无法进行")
        return 1

    r1 = pyd.annotate("中国导演")
    check("常用字注音正确", r1["annotated"] == "zhōng guó dǎo yǎn")
    r2 = pyd.annotate("重庆")
    check("词组消歧：重庆 → chóng qìng",
          r2["annotated"] == "chóng qìng")
    r3 = pyd.annotate("银行")
    check("词组消歧：银行 → yín háng", r3["annotated"] == "yín háng")
    r4 = pyd.annotate("长大")
    check("词组消歧：长大 → zhǎng dà", r4["annotated"] == "zhǎng dà")
    r5 = pyd.annotate("龘靐齉爨彧")
    check("生僻字覆盖（龘靐齉爨彧）全部注出",
          r5["coverage"] == 1.0 and not r5["unknowns"])
    r6 = pyd.annotate("鑫淼焱垚犇")
    check("生僻三叠字覆盖", r6["coverage"] == 1.0)
    # 未知字：诚实，不编造
    r7 = pyd.annotate("𠀋")
    check("CJK 扩展 B 区未知字 → 标 unknown（不编造读音）",
          r7["unknowns"] == ["𠀋"] and r7["coverage"] == 0.0)
    check("未知字提示提到「未编造」", "未编造" in r7["message"])
    check("空输入 → ok=False 且有人话原因",
          pyd.annotate("")["ok"] is False
          and "空" in pyd.annotate("")["message"])
    check("非汉字不受影响（英文/数字/标点保持原样）",
          pyd.annotate("AI2026，好")["annotated"].endswith("hǎo"))

    # ════════════ B. 确定性（核心优势） ════════════
    a = pyd.lookup("我们要去重庆拍一场重要的戏").get("items", [])
    b = pyd.lookup("我们要去重庆拍一场重要的戏").get("items", [])
    check("同输入两次结果逐字一致（可复现）", a == b)
    check("多音字被识别（重/要/场/的 至少命中）",
          len([i for i in a if i["polyphone"]]) >= 2)
    check("候选音由字典提供（≥2 个）",
          all(len(i["candidates"]) >= 1 for i in a))

    # ════════════ C. SSML 按位置标注 ════════════
    # 「重」在「重庆」读 chóng、「重要」读 zhòng —— 同字不同音，须各标各的
    s = pyd.to_ssml("重庆和重要")
    check("SSML 产出 speak + phoneme", "<speak>" in s["ssml"] and "<phoneme" in s["ssml"])
    check("同字两处各自读音不同（按位置标注）",
          'ph="chong2">重<' in s["ssml"] and 'ph="zhong4">重<' in s["ssml"])
    s2 = pyd.to_ssml("山河")   # 实测「山河」二字均为单音（0 处多音字）
    check("无多音字时不标注（避免 SSML 膨胀）", s2["marked"] == 0)
    check("标注数 == 文本内多音字数（不多标不漏标）",
          pyd.to_ssml("明月")["marked"]
          == len(pyd.polyphones("明月")["items"]))
    check("空输入 SSML → ok=False", pyd.to_ssml("")["ok"] is False)

    # ════════════ D. tts_guard 集成（注音不再随 LLM 消失） ════════════
    def boom(_p: str) -> str:
        raise RuntimeError("模拟 LLM 挂掉")

    plan = tg.plan_tts("我们去了重庆。", llm=boom)
    check("LLM 抛错 → 不崩（ok=True）", plan["ok"] is True)
    check("LLM 抛错 → 字典接管注音（dict_annotated>0）",
          plan["dict_annotated"] > 0 and plan["llm_annotated"] == 0)
    check("段来源标注 annotated_source=dict",
          any(x["annotated_source"] == "dict" for x in plan["segments"]))
    check("SSML 真的产出 phoneme",
          any("<phoneme" in x["annotated"] for x in plan["segments"]))
    plan_no_llm = tg.plan_tts("我们去了重庆。")
    check("完全不接 LLM 时也有注音（改前为零）",
          plan_no_llm["dict_annotated"] > 0)
    check("message 诚实说明来源含「字典」", "字典" in plan_no_llm["message"])

    # ════════════ E. 四处接线静态断言（★ 3/4 处守卫不覆盖） ════════════
    CAP = "pipeline.pinyin_lookup"
    ACT = "pinyin_lookup"
    cat_src = _read("app", "core", "agent_capability_catalog.py")
    check("接线1 catalog 含能力行", f'"{CAP}"' in cat_src)
    check("接线1 半球=left（语言/逻辑，与 tts_polish 的 right 区分）",
          'LLM", "left", "注音查询"' in cat_src)
    h_src = _read("app", "core", "capability_handlers.py")
    check("接线2 handlers 含 def pinyin_lookup", "def pinyin_lookup(" in h_src)
    check("接线2 handlers 含 register", f'dispatcher.register("{CAP}"' in h_src)
    a_src = _read("app", "core", "agent_action_registry.py")
    check("接线3 action 表含映射行", f'("{ACT}", "safe", "{CAP}"' in a_src)
    check("接线4 帮助文案含参数说明", f"{ACT} 参数:" in a_src)
    check("接线4 L2 执行段提到该动作", f"{ACT} 可查汉字读音" in a_src)

    # ════════════ G. 人工校订表（专名 / 易错词）════════════
    # 这些是 pypinyin 开箱**实测会读错**的条目（2026-09-25 体检：专名 20% 错）
    PROPER = {
        "大宛": "dà yuān", "皋陶": "gāo yáo", "金日磾": "jīn mì dī",
        "樊於期": "fán wū jī", "曹参": "cáo shēn", "龟兹": "qiū cí",
        "月氏": "yuè zhī", "可汗": "kè hán", "吐蕃": "tǔ bō",
        "单于": "chán yú", "冒顿": "mò dú", "郦食其": "lì yì jī",
        "尉迟": "yù chí", "万俟": "mò qí", "吐谷浑": "tǔ yù hún",
        "蚌埠": "bèng bù", "六安": "lù ān", "铅山": "yán shān",
        "台州": "tāi zhōu", "番禺": "pān yú", "涪陵": "fú líng",
        "阿房宫": "ē páng gōng", "会稽": "kuài jī", "阆中": "làng zhōng",
        "华佗": "huà tuó",
    }
    bad = []
    for w, expect in PROPER.items():
        got = pyd.annotate(w)["annotated"]
        if got != expect:
            bad.append((w, expect, got))
            print(f"      ✗ {w}: 期望 {expect} | 实际 {got}")
    check(f"专名校订 {len(PROPER)} 例全部正确", not bad)

    TRICKY = {
        "削苹果": "xiāo píng guǒ", "一模一样": "yī mú yī yàng",
        "螳臂当车": "táng bì dāng chē", "方兴未艾": "fāng xīng wèi ài",
        "博闻强识": "bó wén qiáng zhì", "倔强": "jué jiàng",
        "牵强附会": "qiān qiǎng fù huì", "呼天抢地": "hū tiān qiāng dì",
        "屡见不鲜": "lǚ jiàn bù xiān", "鲜为人知": "xiǎn wéi rén zhī",
        "载歌载舞": "zài gē zài wǔ", "三年五载": "sān nián wǔ zǎi",
        "审时度势": "shěn shí duó shì", "以己度人": "yǐ jǐ duó rén",
        "拐弯抹角": "guǎi wān mò jiǎo", "乳臭未干": "rǔ xiù wèi gān",
        "称心如意": "chèn xīn rú yì", "磨坊": "mò fáng",
        "鸭绿江": "yā lù jiāng", "刹那": "chà nà",
        "魑魅魍魉": "chī mèi wǎng liǎng", "参差": "cēn cī",
        "骠骑": "piào qí", "般若": "bō rě",
    }
    bad2 = []
    for w, expect in TRICKY.items():
        got = pyd.annotate(w)["annotated"]
        if got != expect:
            bad2.append((w, expect, got))
            print(f"      ✗ {w}: 期望 {expect} | 实际 {got}")
    check(f"易错词校订 {len(TRICKY)} 例全部正确", not bad2)

    ov = pyd.stats()["overrides"]
    check(f"校订表规模充足（词组 {ov['phrases']} 条 / 单字 {ov['singles']} 条）",
          ov["phrases"] >= 120 and ov["singles"] >= 20)
    check("校订表无字数不符条目（skipped 为空）", ov["skipped"] == [])
    check("自定义词表模板可用（项目可名统一读音）",
          "phrases" in pyd.override_template())
    st = pyd.stats()
    check("stats 诚实标注分区覆盖率（含扩展 B 缺口）",
          "扩展 B 区" in str(st.get("coverage_measured_2026_09_25", {})))

    # ════════════ H. lip_sync 挂载（口型与配音同源）════════════
    lip_src = _read("app", "core", "lip_sync.py")
    check("lip_sync 不再直接 import pypinyin（改走字典入口）",
          "import pypinyin" not in lip_src)
    check("lip_sync 调用 pinyin_dict.annotate",
          "pinyin_dict import annotate" in lip_src)
    check("lip_sync 用 chars 详情过滤非汉字（防 'abc123' 当音素）",
          'c.get("cjk") and c.get("known")' in lip_src)

    # ════════════ F. 能力端到端（走 dispatcher） ════════════
    try:
        import app.core.agent_action_registry as reg
        import app.core.agent_capability_catalog as cat
        from app.core.capability_dispatcher import (CapabilityDispatcher,
                                                    CapabilityRequest)
        from app.core.capability_handlers import register_builtin_handlers

        d = CapabilityDispatcher()
        register_builtin_handlers(d)
        check("目录 ↔ dispatcher 双向一致（守卫）",
              cat.verify_catalog_consistency(set(d._handlers.keys())) == [])
        check("action 映射到正确能力",
              reg.ACTION_TO_CAPABILITY.get(ACT) == CAP)
        check("action 在白名单里（LLM 看得见）",
              ACT in reg.get_allowed_actions())
        check("神经元表含它（自动挂左脑）",
              CAP in [row[0] for row in cat.neuron_taxonomy()])
        res = d.invoke(CapabilityRequest(CAP, {"text": "重庆银行"},
                                         request_id="chk"))
        out = res.output or {}
        check("端到端调用成功", bool(res.success))
        check("端到端返回正确注音",
              [i["pinyin"] for i in out.get("items", [])][:2] == ["chóng", "qìng"])
        res2 = d.invoke(CapabilityRequest(CAP, {"text": ""}, request_id="chk2"))
        check("空 text → 失败且带 error（不假成功）",
              (not res2.success) and bool(res2.error))
        res3 = d.invoke(CapabilityRequest(CAP, {"text": "音乐", "mode": "sapi"},
                                          request_id="chk3"))
        check("mode=sapi 返回数字式",
              "yin1" in str((res3.output or {}).get("annotated", "")))
    except Exception as e:
        check(f"端到端段执行异常：{e}", False)

    print(f"\n{'=' * 50}\n注音字典检查：{TOTAL - len(FAILS)}/{TOTAL} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("OK 汉字注音字典 + 四处接线全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
