"""Conservative action classification shared by previews and settlement."""

import re


ACTION_WORDS = {
    "rest": ("休息", "睡觉", "睡眠", "喝茶", "用餐", "治疗", "疗伤", "沐浴"),
    "investigate": ("调查", "搜索", "观察", "分析", "追踪", "询问", "线索"),
    "social": ("交涉", "说服", "安慰", "邀请", "聊天", "道歉", "谈判", "请教"),
    "survival": ("赶路", "探索", "潜入", "闪避", "防御", "治疗", "露营", "飞行"),
    "travel": ("赶路", "奔跑", "搜索", "调查", "潜入", "飞行", "探索"),
}
NON_ACTION = re.compile(r"不(?:会|能|想|要|再|打算)?|没(?:有|能)?|未|别|拒绝|无法|不能|打算|计划|准备|想要|想先|如果|假如|是否|能否|听说|提到")


def performed_text(text):
    """Quoted speech and unexecuted intentions are not completed actions."""
    text = str(text or "").split("【语言】", 1)[0]
    if text.startswith(("语言：", "语言:")):
        return ""
    text = re.sub(r'"[^"\n]*"|“[^”\n]*”|「[^」\n]*」', "", text)
    parts = re.split(r"[，,。；;！!？?\n]", text)
    return "；".join(part for part in parts if part.strip() and not NON_ACTION.search(part))


def classify_action(text):
    effective = performed_text(text)
    return {"version": 1, "status": "performed" if effective.strip("（）() ") else "intent_only",
            "effective_text": effective,
            "kinds": [kind for kind, words in ACTION_WORDS.items() if any(word in effective for word in words)]}


def action_context(text):
    action = classify_action(text)
    return ("行动结算：" + str(action) + "。只对实际执行的动作结算；计划、否定、引语不产生对应收益。"
            "后端已裁定的活动、物品、时间与关系结果优先，不得在旁白中改写为另一结果。")
