# -*- coding: utf-8 -*-
"""中文 TTS 多音字/数字读法修正——确定性规则漏斗（edge-tts / qwen-tts 实跑判例沉淀）。

为什么需要这个库
----------------
edge-tts 不支持注音/拼音/SSML，多音字读错（「代码一行没写」读成「一 xíng 没写」）
只能靠**同音字替换**修正：TTS 输入侧把易错字换成同音字，读音归位；字幕/显示侧读
原始文本不受影响。阿拉伯数字同理——TTS 前端对「10年」常逐位读成「一零年」，
本库默认转中文数量读法（十年），年份/型号/IP 等语境自动豁免。

核心设计
--------
1. **只改 TTS 输入，不改原文**：调用方把修正后的文本送 TTS，界面/字幕仍显示原文。
2. **确定性规则优先**：每条规则来自真实成片误读实证（规则注释保留日期与出处），
   零歧义词直接钉死，比 LLM 判读稳。
3. **LLM 消歧可插拔**：剩余多音字上下文可选交给 LLM 判读音，再按拼音→同音替身表
   替换（LLM 只判读音、不自造替身字）。默认关闭；接法见 `set_llm_chat`。
4. **fail-open**：LLM 网络异常/解析失败一律回落确定性规则结果，不阻塞生产。

移植说明：本库移植自一条中文内容产线的内部 SSOT 模块，规则表按「成片实拍误读 →
用户耳朵抓到 → 钉死一条规则」的节奏持续积累，每条注释保留实证出处。
"""
from __future__ import annotations

import re
import sys
from typing import Callable, Optional

__all__ = [
    "POLYPHONE_RULES",
    "POLYPHONE_WATCH_CHARS",
    "PINYIN_SUBSTITUTES",
    "apply_polyphone_substitutions",
    "normalize_arabic_numerals",
    "llm_polyphone_disambiguate",
    "set_llm_chat",
    "uncovered_polyphone_hits",
    "uncovered_arabic_digits",
    "warn_uncovered_watch",
]

# ── 替换规则表 ──────────────────────────────────────────
# 每条 = (规则名, 编译正则, 替换串, 释义)。正则用捕获组/断言保留上下文，只换目标字。
# 已实证易错（zh-CN 神经声）优先；疑似项先不进表——由 uncovered_polyphone_hits
# 反查兜底。新增规则的纪律：
# 1. 上下文必须足够窄——只在该搭配确实易读错时替换（「一[量词]行+代码」xíng→航）；
#    本来就读对的常见词（银行/行业 háng，行动/执行 xíng）不碰。**零歧义搭配即使
#    常见也可确定性入表**：行情只有 hángqíng 一读，实证 LLM 也会误判 xíng——
#    零歧义词走确定性规则比走 LLM 稳。
# 2. 替换字必须同音（含声调）——「还 huán」用「环 huán」，不用「换 huàn」
#    （声调不同，TTS 会读出别扭的四声）。
POLYPHONE_RULES: list[tuple[str, re.Pattern[str], str, str]] = [
    (
        # 实证：「代码一行没写」被读成「一 xíng 没写」。行 háng（行列义）
        # 前接数量词、后接代码类名词/「没写」时替换为同音「航」。
        "hang_row",
        re.compile(r"([一二两三四五六七八九十几多数百千\d]+)行(?=(?:代码|注释|文字|文案|命令|配置|命令行|都没写|没写|都不写))"),
        r"\g<1>航",
        "行 háng（一 X 行代码）→ 航",
    ),
    (
        # 成片实拍：三处「行情」全被读 xíng 情（耳朵抓到）。病根在 LLM 消歧层：
        # LLM 把零歧义的 行情 误判 xing2。行情只有 hángqíng 一读、无例外搭配，
        # 确定性同音「航」钉死——行情帖/行情主轴/最新行情/接单的行情全命中；
        # 规则先于 LLM 跑，LLM 再见不到该字。
        "hang_market",
        re.compile(r"行(?=情)"),
        "航",
        "行 háng（行情）→ 航",
    ),
    (
        # 成片实拍：「用命令行操作」被克隆音色读成「命令 xíng 操作」（耳朵抓到）。
        # 命令行是零歧义词（只有 mìnglìngháng 一读），同「行情」判例：确定性同音
        # 「航」钉死，规则先于 LLM；「行」已撤出 LLM 候选，枚举漏网只能靠扩规则补。
        # 用后行断言只换该字，命令行操作/工具/界面/在命令行里全命中。
        "hang_cmdline",
        re.compile(r"(?<=命令)行"),
        "航",
        "行 háng（命令行）→ 航",
    ),
    (
        # 还 huán（归还义）：还给/还钱/还回来/还了——edge-tts 常误读 hái。
        # 同音「环 huán」替换（换是 huàn 四声，不能用）。
        "huan_return",
        re.compile(r"还(?=(?:给|钱|回来|了|不了|回去))"),
        "环",
        "还 huán（还给/还钱）→ 环",
    ),
    (
        # 成片实拍：「认识了很多同行」被读 tóng xíng（耳朵抓到）。同业者义
        # tóngháng 整词换同音「同航」；伴行义 xíng（一路同行/结伴同行）负向豁免。
        "tonghang_peer",
        re.compile(r"(?<!一路)(?<!结伴)同行"),
        "同航",
        "行 háng（同行=同业者）→ 航",
    ),
    (
        # 成片实拍：「直接搬到国内行不通」被克隆音色读「héng 不通」（耳朵抓到）。
        # 可行义 xíng 的动补框架「行不通/行得通」同构，一并入表；「可行/行动/执行」
        # 等其余 xíng 框架未实证误读，不碰。同音同调：形 xíng（二声）对 行 xíng。
        "xing_feasible",
        re.compile(r"行(?=(?:不通|得通))"),
        "形",
        "行 xíng（行不通/行得通）→ 形",
    ),
    (
        # 对照评测实证：LLM 三轮都把「数不胜数」的一个 数（shǔ，计数义）判成 shù。
        # shǔ 无歧义的成语/口语搭配确定性入表——数不胜数/数不清，同音「属 shǔ」
        # 钉死，规则先于 LLM。
        "shu_count",
        re.compile(r"数(?=(?:不胜数|不清))"),
        "属",
        "数 shǔ（数不胜数/数不清）→ 属",
    ),
    (
        # 成片试听实拍：「榜得真」被读成「榜 de 真」（耳朵抓到）。得 děi 无同调
        # 同音字（纪律 2 同音替换走不通），落到 TTS 输入侧同义改写：能愿动词
        # 得→同义「必须」（声音自然、语义同构）；字幕/显示读原始文本不受影响。
        # 上下文收窄：仅 得+真/公开/让/先/有/去/试（口播能愿高频），前接
        # 取得/获得/觉得/值得/赢得/记得/懂得/显得/免得 时豁免（防
        # 「取得真经/觉得真不错/记得先…」误替换）。
        "dei_modal",
        re.compile(r"(?<![取获觉赢值记懂显免])得(?=(?:真|公开|让|先|有|去|试))"),
        "必须",
        "得 děi（得真/得公开/得先）→ 必须（同义改写，无同音字）",
    ),
]

# 疑似但不进表的（防误替换）：更 gēng（更改/更新）、重 chóng（重来）、教 jiāo（教书）
# 声学模型通常读对——留在 WATCH_CHARS 里由 uncovered_polyphone_hits 反查兜底，
# 实证误读再扩表。得 děi 无同音字，走表内 dei_modal 的同义改写。
_ACTIVE_RULES = POLYPHONE_RULES

# ── 监控字表 ────────────────────────────────────────────
# 文本里出现且未被规则覆盖时提示人工确认的多音字（AI/技术解说高频）。
# 不在表里的多音字默认「常见词，声学模型通常读对」。
POLYPHONE_WATCH_CHARS = "行还更重长干弹教数传得露落省处卡种差切便泡折琢磨"


# 一次替换：TTS 输入侧调用。
def apply_polyphone_substitutions(text: str) -> str:
    """按规则表替换多音字为同音字（仅 TTS 读音用；字幕/显示原始文本不经过这里）。"""
    if not text:
        return text
    for _name, pat, repl, _desc in _ACTIVE_RULES:
        text = pat.sub(repl, text)
    return text


# ── LLM 上下文多音字消歧（可选）──────────────────────────
# 病根：上方规则表是「窄正则枚举」，方向单一（huán 义→环），反向漏判（hái 义被引擎
# 读 huán）证明枚举追不完——TTS 前端对多音字的判读本身不稳，逐词打补丁不可泛化。
# 泛化修法：拿**全句上下文**让 LLM 判每个多音字的实际读音，再按下方 SSOT
# 拼音→同音替身表替换——LLM 只判读音不自造替身字（同音含声调由表保证），
# 判读不进表（无安全替身）即原字放行。仍只作用于 TTS 输入，字幕/显示原文不受
# 影响。fail-open：无回调/网络异常/超时一律回落确定性规则结果，不阻塞生产。
PINYIN_SUBSTITUTES: dict[str, str] = {
    # 键=拼音+声调数字；值=同音同调替身字（常见字，TTS 稳定读对）。
    "hai2": "孩", "huan2": "环",
    "hang2": "航", "xing2": "形",
    "chang2": "常", "zhang3": "掌",
    "chong2": "虫", "zhong4": "众",
    "jiao1": "交", "jiao4": "叫",
    "chuan2": "船", "zhuan4": "赚",
    "shu3": "属", "shu4": "树",
    # 无安全替身的读音不入表（得 de/děi 等）——LLM 判出即放行原字。
    # 「干」两读均撤（实证）：LLM 把「顶着干」（gàn 动词义）误判 gan1 → 强制错读
    # 烤进音频；gān 义（干净/干杯）为常见词、引擎原生读对，替身收益<误判代价——
    # 两读一律放行原字交引擎自判。
}
# 有替身可换的多音字集合（只把这些送 LLM，减少误替换面与调用面）。
# 「行」不送：确定性规则已把五类实证误读搭配钉死（一行代码/行情/命令行/同行/
# 行不通·行得通），其余 行 搭配（银行·行业 háng，行动·执行·进行·不行 xíng）
# 都是引擎原生读对的零歧义词；LLM 再判 行 只剩误判代价——交回引擎自判。
# 「教」同理：教你·教书 jiāo 与 教师·教程·教练 jiào 均为引擎原生常见词。
_LLM_POLYPHONE_CHARS = "还长重传数"

# 声调符号→数字（容错 LLM 回 á 式注音）
_TONE_MARKS = {
    **{c: base for c, base in zip("āáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜ", [
        *(f"a{n}" for n in range(1, 5)), *(f"o{n}" for n in range(1, 5)),
        *(f"e{n}" for n in range(1, 5)), *(f"i{n}" for n in range(1, 5)),
        *(f"u{n}" for n in range(1, 5)), *(f"v{n}" for n in range(1, 5))])},
}

_LLM_PINYIN_CACHE: dict[str, str] = {}

# 可插拔 LLM 回调：(system_prompt, user_prompt) -> 原始回复文本。默认 None=关闭。
# 接法示例见 README；回调内部自行处理客户端/鉴权/超时。
LLMChat = Callable[[str, str], str]
_llm_chat: Optional[LLMChat] = None


def set_llm_chat(fn: Optional[LLMChat]) -> None:
    """注册 LLM 消歧回调（同步函数，抛异常会被 fail-open 吞掉回落规则结果）。"""
    global _llm_chat
    _llm_chat = fn


def llm_polyphone_disambiguate(text: str) -> str:
    """LLM 上下文多音字消歧：判读音→SSOT 同音替身表替换（fail-open，默认关闭）。

    在 apply_polyphone_substitutions **之后**调用（确定性规则先走，LLM 只管剩余的）。
    未注册回调 / 无多音字 / 任何异常 → 原样返回（=关闭时的行为）。
    """
    if not text or _llm_chat is None:
        return text
    hits = [(i, ch) for i, ch in enumerate(text) if ch in _LLM_POLYPHONE_CHARS]
    if not hits:
        return text
    cached = _LLM_PINYIN_CACHE.get(text)
    if cached is not None:
        return cached
    try:
        import json as _json

        ctx = 8
        marks = "；".join(
            f"{ch}#{n + 1}（上下文「…{text[max(0, i - ctx):i]}〔{ch}〕{text[i + 1:i + 1 + ctx]}…」）"
            for n, (i, ch) in enumerate(hits)
        )
        sys_p = (
            "你是中文多音字注音器。给句中编号的多音字标实际读音，按上下文语义判。"
            "只输出 JSON。拼音用字母+声调数字（如 hai2、huan2、chang2、zhang3、"
            "chong2、zhong4、chuan2、zhuan4、shu3、shu4、de2、de5、dei3）。"
        )
        usr_p = f"句子：{text}\n多音字：{marks}\n输出 {{\"readings\":[{{\"i\":1,\"char\":\"还\",\"pinyin\":\"hai2\"}}]}}"
        raw = _llm_chat(sys_p, usr_p)
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        data = _json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        subs: dict[int, str] = {}
        for rd in data.get("readings", []):
            i, ch, py = rd.get("i"), rd.get("char"), (rd.get("pinyin") or "").strip().lower()
            if any(c in py for c in "āáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜ"):
                py = py.rstrip("12345")  # 容错「声调符号+数字」混写
            py = py.translate(_TONE_MARKS)
            if not (isinstance(i, int) and 1 <= i <= len(hits) and py in PINYIN_SUBSTITUTES):
                continue
            pos, hit_ch = hits[i - 1]
            if ch == hit_ch and PINYIN_SUBSTITUTES[py] != hit_ch:
                subs[pos] = PINYIN_SUBSTITUTES[py]
        if not subs:
            _LLM_PINYIN_CACHE[text] = text
            return text
        out = "".join(subs.get(i, ch) for i, ch in enumerate(text))
        detail = "，".join(f"{text[i]}→{c}" for i, c in subs.items())
        print(f"  [ttscnfix:poly-llm] {detail}", flush=True)
        _LLM_PINYIN_CACHE[text] = out
        return out
    except Exception:  # fail-open：网络/解析/超时一律回落确定性结果
        return text


# ── 反查工具 ────────────────────────────────────────────
def uncovered_polyphone_hits(text: str, *, context_chars: int = 6) -> list[str]:
    """找「监控字出现、但无规则覆盖」的上下文（出提示，不硬拦）。

    相邻监控字（间隔 ≤ context_chars）合并为一个片段，避免重叠碎片刷屏。
    返回形如 「…三处地方…」 的去重片段列表（按出现顺序）。空文本返回空列表。
    """
    if not text:
        return []
    covered: list[tuple[int, int]] = []  # 被规则匹配消费掉的字符区间（含捕获组）
    for _name, pat, _repl, _desc in _ACTIVE_RULES:
        for m in pat.finditer(text):
            covered.append((m.start(), m.end()))
    # 未覆盖的监控字位置 → 相邻合并成簇
    positions = [
        i for i, ch in enumerate(text)
        if ch in POLYPHONE_WATCH_CHARS and not any(s <= i < e for s, e in covered)
    ]
    hits: list[str] = []
    cluster: list[int] = []
    for i in positions + [len(text) + 99]:  # 哨兵冲刷最后一簇
        if cluster and i - cluster[-1] > context_chars:
            s, e = cluster[0], cluster[-1]
            frag = f"…{text[max(0, s - context_chars):e + context_chars + 1]}…"
            if frag not in hits:
                hits.append(frag)
            cluster = []
        cluster.append(i)
    return hits


# 渲染路提示去重（同一上下文一次渲染只报一次）
_WATCH_WARNED: set[str] = set()


def warn_uncovered_watch(text: str) -> None:
    """读音风险提示：未覆盖监控字上下文打进日志（去重防刷屏）。

    只提示不硬拦——监控字多为引擎常读对的常见词（觉得/重点/上传），硬拦会把
    每次合成都变成人工确认；误读实证后再入 POLYPHONE_RULES 或改词面。
    """
    for frag in uncovered_polyphone_hits(text):
        if frag in _WATCH_WARNED:
            continue
        _WATCH_WARNED.add(frag)
        print(f"  [ttscnfix:poly-watch] ⚠ 未覆盖多音字上下文{frag}"
              "（人工确认读音；误读实证后入 POLYPHONE_RULES 或改词面）", flush=True)


# ── 阿拉伯数字 → 中文数量读法 ──────────────────────────────
# 实证：「剪片10年」被 qwen-tts 逐位读成「剪片一零年」（edge-tts 同病）。中文
# 解说稿的数字读法是「数量读法」（十年/七万/一百零一），逐位读只对日历年
# （2025年→二零二五）和编号类 ID 正确——所以默认转数量读法，年份/ID/型号三类豁免。
_CN_DIGITS = "零一二三四五六七八九"
_CN_SMALL = ["", "十", "百", "千"]
_CN_BIG = ["", "万", "亿"]  # >8 位已豁免，万亿级不会出现

# 独立「二」后接这些量词 → 换「两」（两个月/两倍/两到三次/两亿）；「第2」序数保留二。
_MEASURE_AFTER_TWO = set(
    "个位次条年天周月单倍家块美元元小时分钟秒钟章层楼批部份名岁号题步点张封则款折场队种只件套轮遍回声万像素度到亿"
)

# 计数单位集（日历年判别用）：19xx/20xx 默认按年逐位读（二零二六=正确读法），
# 仅当紧跟这些单位（2025个/2025万）才按数量转。「年」刻意不在集内——
# 「2025年」就是年语境豁免；「从2025到2026年」的「到」也不在，防止年份区间误转。
_COUNT_UNITS = set(
    "个条倍次分秒小时天周月岁张位名人块家单集万只场轮批部份号题步封则款折队种件套回声像素度多余"
)

# 两位数代际读法（逐位读：九零后、零零后）。100% 确定，无歧义。
_TWO_DIGIT_ERA_SUFFIXES = "后"  # 90后→九零后、00后→零零后、95后→九五后

# 两位数 + 「年」的年份简写触发语境（后接下列词 = 指某一年，逐位读：九八年）。
# 不在此列的「XX年」默认数量读法（十年/二十年）。剪片10年/工作20年 = 时长，不触发。
_TWO_DIGIT_YEAR_NEXT = (
    "出生", "毕业", "生的", "进的", "来的", "的小伙子", "的小伙",
    "开始", "进入", "参加", "出道", "回国", "来到", "创业",
)

# 紧邻这些 ASCII 字符（含全角乘号×）的数字 = 型号/版本/ID 语境，不转
# （GPT-4 / v2 / 1280x800 / 24/7 / 7×24）。「.」不进集合：单点小数（1.2 版本）
# 中文口播本就念「一点二」；多点链由正则先匹配豁免。
_ADJACENT_ASCII = set("AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRrSsTtUuVvWwXxYyZz_+-/×")

# 多点链（IP/版本号 192.168.1.1、1.2.3）整体豁免优先匹配；普通数字 token 可带 % 。
_NUM_TOKEN_RE = re.compile(r"\d+(?:\.\d+){2,}|\d+(?:\.\d+)?%?")


def _group_to_cn(g: int) -> str:
    """1..9999 → 节内中文（内部零折叠、尾零省略）。"""
    s = ""
    zero_pending = False
    for pos in (3, 2, 1, 0):
        d = (g // 10 ** pos) % 10
        if d == 0:
            if s:
                zero_pending = True
            continue
        if zero_pending:
            s += "零"
            zero_pending = False
        s += _CN_DIGITS[d] + _CN_SMALL[pos]
    return s


def _int_to_cn(n: int) -> str:
    """非负整数 → 中文数量读法。10→十（非一十）；110→一百一十；101→一百零一；
    100000001→一亿零一；20000000→二千万（「两」换写由 _cn_liang_adjust 处理）。"""
    if n == 0:
        return "零"
    groups: list[int] = []
    x = n
    while x:
        groups.append(x % 10000)
        x //= 10000
    out = ""
    pending_zero = False
    for gi in range(len(groups) - 1, -1, -1):
        g = groups[gi]
        if g == 0:
            pending_zero = True  # 空节：零在下个非零节前补一次
            continue
        seg = _group_to_cn(g)
        if not out and 10 <= g <= 19:
            seg = seg[1:]  # 最高节 10-19 去前导「一」：十/十五/十九
        if out and (pending_zero or g < 1000):
            seg = "零" + seg  # 节间空位/低节缺位：一亿零一 / 两千零一
        out += seg + (_CN_BIG[gi] if gi < len(_CN_BIG) else "")
        pending_zero = False
    return out


def _cn_liang_adjust(cn: str) -> str:
    """千/万/亿 起首的「二」换「两」（两千/两万/两千万）；二百/二十保留二。"""
    if len(cn) >= 2 and cn[0] == "二" and cn[1] in "千万亿":
        return "两" + cn[1:]
    return cn


def normalize_arabic_numerals(text: str) -> str:
    """TTS 输入数字归一化：阿拉伯数字 → 中文数量读法（幂等，输出无 \\d）。

    豁免（原样保留）：型号/ID 邻接（ASCII 字母/加减斜杠）、IP/版本多点链、
    19xx/20xx+年（日历年逐位读，显式转中文「二零二五」不再赌引擎）、>8 位长号、
    全角数字（语料不出现）。
    """
    if not text or not re.search(r"\d", text):
        return text

    def _repl(m: "re.Match[str]") -> str:
        tok = m.group(0)
        prev = text[m.start() - 1] if m.start() else ""
        nxt = text[m.end()] if m.end() < len(text) else ""
        if tok.count(".") >= 2:  # IP / 版本号多点链
            return tok
        is_pct = tok.endswith("%")
        body = tok[:-1] if is_pct else tok
        int_s, _, frac_s = body.partition(".")
        if not is_pct and not frac_s and re.fullmatch(r"(19|20)\d{2}", int_s):
            # 日历年判别（「2026 年」带空格也命中）：跳过空白找真后继，
            # 非计数单位（年/到/句读/结尾）→ 年语境逐位读「二零二六」；
            # 2025个/2025万 这类计数语境才按数量转。
            j = m.end()
            while j < len(text) and text[j] in " \t\n":
                j += 1
            nxt_eff = text[j] if j < len(text) else ""
            if nxt_eff not in _COUNT_UNITS:
                # 实拍：引擎把豁免原样的「2025 年」按数量读法读成「两千零二十五 年」
                # （逐位读预期落空）。不再赌引擎行为：年语境显式转逐位中文。
                # 字幕/显示读原始文本（阿拉伯数字），画面不受影响。
                return "".join(_CN_DIGITS[int(c)] for c in int_s)
        if len(int_s) == 2 and prev != "第":
            if nxt in _TWO_DIGIT_ERA_SUFFIXES:
                # 两位数代际「X0后/XX后」：逐位读（九零后、九五后、零零后）
                return "".join(_CN_DIGITS[int(c)] for c in int_s)
            if nxt == "年":
                # 两位数 + 年：后接年份语境（出生/毕业/的小伙子…）→ 逐位读「九八年」；
                # 否则默认数量读法「十年/二十年」（剪片10年/工作20年=时长）。
                # 实证：「98 年」被读「九十八年」，应为「九八年」。
                after = text[m.end() + 1:]  # 跳过「年」
                if any(after.startswith(w) for w in _TWO_DIGIT_YEAR_NEXT):
                    return "".join(_CN_DIGITS[int(c)] for c in int_s)
        if len(int_s) > 8:  # 电话/QQ 号风险，宁可不转（uncovered_arabic_digits 反查兜底）
            return tok
        if (prev and prev in _ADJACENT_ASCII) or (nxt and nxt in _ADJACENT_ASCII):
            return tok  # GPT-4 / v2 / 1280x800 / 24/7 型号 ID 语境
        cn = _int_to_cn(int(int_s))
        if frac_s:
            cn += "点" + "".join(_CN_DIGITS[int(c)] for c in frac_s)
        else:
            cn = _cn_liang_adjust(cn)
        if is_pct:
            return "百分之" + cn
        if cn == "二" and nxt in _MEASURE_AFTER_TWO and prev != "第":
            return "两"  # 独立「二」+量词 → 两个月/两倍；「第2」序数保留二
        return cn

    return _NUM_TOKEN_RE.sub(_repl, text)


# ── 反查（数字侧）────────────────────────────────────────
def uncovered_arabic_digits(text: str, *, context_chars: int = 6) -> list[str]:
    """归一化后仍残留的阿拉伯数字上下文（豁免类：型号/ID/年份/长号）→ 提示
    供人工确认豁免是否正确，防止把该读数量的数字漏在豁免里。"""
    if not text:
        return []
    norm = normalize_arabic_numerals(text)
    hits: list[str] = []
    for m in re.finditer(r"\d+(?:\.\d+)*", norm):
        frag = f"…{norm[max(0, m.start() - context_chars):m.end() + context_chars + 1]}…"
        if frag not in hits:
            hits.append(frag)
    return hits
