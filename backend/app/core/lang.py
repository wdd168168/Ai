"""多语言引擎：脚本识别 + 台湾用语本地化 + 简繁一致性校验。

支持：zh-CN（简体中文）/ zh-TW（台湾繁体国语）/ nan-TW（台语·闽南语）/
en（英语）/ vi（越南语）/ km（高棉语）。

注意：zh-TW=台湾国语（繁体），nan-TW=台语（闽南语），两者是独立选项，绝不合并。
"""
from __future__ import annotations

import re

import zhconv

LANGS = {
    "zh-CN": "简体中文",
    "zh-TW": "台湾繁体国语",
    "nan-TW": "台语（闽南语）",
    "en": "英语",
    "vi": "越南语",
    "km": "高棉语",
}

# 台湾用语（简体 → 台湾说法）。只替换词，不整句硬翻。
TW_TERMS = {
    "软件": "軟體", "硬件": "硬體", "网络": "網路", "信息": "資訊", "视频": "影片",
    "短信": "簡訊", "默认": "預設", "支持": "支援", "打印": "列印", "打印机": "印表機",
    "移动": "行動", "质量": "品質", "程序": "程式", "程序员": "程式設計師", "数据库": "資料庫",
    "鼠标": "滑鼠", "内存": "記憶體", "服务器": "伺服器", "硬盘": "硬碟", "笔记本电脑": "筆記型電腦",
    "公交车": "公車", "出租车": "計程車", "自行车": "腳踏車", "地铁": "捷運", "土豆": "馬鈴薯",
    "方便面": "泡麵", "盒饭": "便當", "熊猫": "貓熊", "硅谷": "矽谷", "项目": "專案",
    "优化": "優化", "登录": "登入", "注册": "註冊", "账号": "帳號", "密码": "密碼",
    "星期": "星期", "后台": "後台", "前台": "前台", "视频通话": "視訊通話", "截图": "截圖",
    "保存": "儲存", "文件夹": "資料夾", "刷新": "重新整理", "取消": "取消", "确认": "確認",
    "芯片": "晶片", "人工智能": "人工智慧", "打印机没墨": "印表機沒墨",
    "充电宝": "行動電源", "摩托车": "機車", "垃圾分类": "垃圾分類", "幼儿园": "幼兒園",
    "本科": "大學部", "研究生": "研究所", "盒装": "盒裝", "酸奶": "優格", "三文鱼": "鮭魚",
}

# 台语/闽南语强特征词（不含「嘛/啦/喔」这类国语也常用的语气词）
NAN_STRONG = {
    "恁", "阮", "毋", "佮", "攏", "厝", "咱", "佇", "啥物", "佗位", "按怎",
    "食飽", "拍謝", "無要緊", "好勢", "閣", "沓", "咧講", "伊", "遮的",
}
NAN_ROMAN = re.compile(r"\b(tsiah|bô|lí|guá|lín|tsiok|kám|hōo|tsit|bē|gún)\b", re.I)


def _nan_score(text: str) -> int:
    score = sum(1 for k in NAN_STRONG if k in text)
    if NAN_ROMAN.search(text):
        score += 2
    return score

SIMPLIFIED_ONLY = set("这们说来对时会后开关问题实现发见东车马电话学习边进还样点热爱门头长飞风")
TRADITIONAL_ONLY = set("這們說來對時會後開關問題實現發見東車馬電話學習邊進還樣點熱愛門頭長飛風")

_KM_RE = re.compile(r"[\u1780-\u17ff]")
_THAI_RE = re.compile(r"[\u0e00-\u0e7f]")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_VI_CHARS = set("ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ")


def has_hangul(text: str) -> bool:
    return bool(re.search(r"[\uac00-\ud7af\u1100-\u11ff]", text))


def detect_lang(text: str) -> str:
    """返回语言代码。用于决定「跟随对方」的语言。"""
    if not text or not text.strip():
        return ""
    t = text.strip()
    if _KM_RE.search(t):
        return "km"
    if _THAI_RE.search(t):
        return "th"
    if _HAN_RE.search(t):
        # 汉字：先判台语特征（要求 ≥2 个强特征，避免把「干嘛」误判成台语），再判简繁
        if _nan_score(t) >= 2:
            return "nan-TW"
        prof = script_profile(t)
        if prof["traditional"] > prof["simplified"]:
            return "zh-TW"
        if prof["simplified"] > prof["traditional"]:
            return "zh-CN"
        # 无区分字：看台港用词
        if any(w in t for w in ("軟體", "資訊", "影片", "簡訊", "網路", "預設", "資料庫")):
            return "zh-TW"
        return "zh-CN"
    if any(c in _VI_CHARS for c in t.lower()):
        return "vi"
    if re.search(r"[a-zA-Z]", t):
        return "en"
    return ""


def to_taiwan_terms(text: str) -> str:
    """把简体用词替换为台湾说法（用于 zh-TW / nan-TW 输出后处理）。"""
    out = text
    # 长词优先，避免"软件"被"软"截断
    for simp, tw in sorted(TW_TERMS.items(), key=lambda kv: -len(kv[0])):
        out = out.replace(simp, tw)
    return out


def s2t(text: str) -> str:
    """简体 → 繁体（zhconv，覆盖常用字与异体）。"""
    return zhconv.convert(text, "zh-tw")


TW_TO_CN = {v: k for k, v in TW_TERMS.items() if v not in ("星期", "前台", "取消", "確認", "截圖")}


def tw_to_cn_terms(text: str) -> str:
    """台湾说法 → 大陆说法（用于 zh-CN 输出后处理）。"""
    out = text
    for tw, cn in sorted(TW_TO_CN.items(), key=lambda kv: -len(kv[0])):
        out = out.replace(tw, cn)
    return out


def t2s(text: str) -> str:
    """繁体 → 简体。"""
    return zhconv.convert(text, "zh-cn")


def _is_simp(c: str) -> bool:
    return bool(re.match(r"[\u4e00-\u9fff]", c)) and zhconv.convert(c, "zh-tw") != c


def _is_trad(c: str) -> bool:
    return bool(re.match(r"[\u4e00-\u9fff]", c)) and zhconv.convert(c, "zh-cn") != c


def script_profile(text: str) -> dict:
    """统计简体字与繁体字数量（用于混用检测）。"""
    simp = sum(1 for c in text if _is_simp(c))
    trad = sum(1 for c in text if _is_trad(c))
    return {"simplified": simp, "traditional": trad}


def check_mixed_script(text: str) -> list[str]:
    """检出简繁混用。返回问题描述列表（空=通过）。"""
    issues = []
    p = script_profile(text)
    if p["simplified"] and p["traditional"]:
        issues.append(f"简繁混用：简体字 {p['simplified']} 个，繁体字 {p['traditional']} 个")
    # 台湾用语一致性：zh-TW 文案里出现大陆用词
    return issues


def apply_language(text: str, lang: str) -> str:
    """按目标语言做输出后处理：台湾用语 + 繁体化，或转回简体。"""
    if lang == "zh-TW":
        return s2t(to_taiwan_terms(t2s(text)))
    if lang == "nan-TW":
        # 台语：保留台语汉字/罗马字，不做简繁强转
        return to_taiwan_terms(text)
    if lang == "zh-CN":
        return tw_to_cn_terms(t2s(text))
    return text


def lang_directive(lang: str, mode: str = "follow") -> str:
    """生成给模型的强约束指令。"""
    names = {
        "zh-CN": "简体中文（大陆用语，不要用台湾用词）",
        "zh-TW": "台湾繁体国语（繁体字 + 台湾用语：軟體/資訊/影片/預設/資料庫，不要出现简体字）",
        "nan-TW": "台语（闽南语）口语，汉字台语用字（阮/恁/毋/佮/咧）或白话字，不要写成国语腔",
        "en": "natural English (no translationese)",
        "vi": "tiếng Việt tự nhiên, có dấu đầy đủ, khẩu ngữ",
        "km": "ភាសាខ្មែរ (Khmer), natural spoken style",
    }
    hint = names.get(lang, lang)
    if mode == "follow":
        return f"用对方的语言回复：{hint}。"
    if mode == "fixed":
        return f"无论对方用什么语言，都必须用 {hint} 回复。"
    return f"当前回复语言：{hint}。"
