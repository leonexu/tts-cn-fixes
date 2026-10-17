# -*- coding: utf-8 -*-
"""LLM 消歧 adapter：可插拔回调 / fail-open / 判读不出替身即放行。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ttscnfix import (  # noqa: E402
    apply_polyphone_substitutions,
    llm_polyphone_disambiguate,
    set_llm_chat,
)


def _fake_llm(sys_prompt: str, usr_prompt: str) -> str:
    # 极简桩：把句中所有「还」判 hai2、「数」判 shu4（覆盖 adapter 全链路即可）。
    # 注意 i 是「多音字命中序号」（1 起），不是字符位置——与模块 hits 对齐。
    start = usr_prompt.index("句子：") + len("句子：")
    sentence = usr_prompt[start:usr_prompt.index("\n多音字")]
    hit_pos = [i for i, ch in enumerate(sentence) if ch in "还长重传数"]
    pinyin = {"还": "hai2", "数": "shu4"}
    readings = [
        {"i": n + 1, "char": sentence[i], "pinyin": pinyin[sentence[i]]}
        for n, i in enumerate(hit_pos)
    ]
    return json.dumps({"readings": readings}, ensure_ascii=False)


def setup_function() -> None:
    set_llm_chat(None)


def test_no_llm_passthrough() -> None:
    # 未注册回调 = 关闭：LLM 层零作用
    assert llm_polyphone_disambiguate("送人玫瑰还月入过千") == "送人玫瑰还月入过千"


def test_llm_disambiguate() -> None:
    # 实证病灶方向（规则表反向漏判）：hái 义被引擎读 huán → LLM 判 hai2 → 孩
    set_llm_chat(_fake_llm)
    got = llm_polyphone_disambiguate(apply_polyphone_substitutions("送人玫瑰还月入过千"))
    assert got == "送人玫瑰孩月入过千", got
    # shu4 → 树（规则层管不到的名词义）
    got2 = llm_polyphone_disambiguate(apply_polyphone_substitutions("两个数对不上"))
    assert got2 == "两个树对不上", got2


def test_fail_open_on_exception() -> None:
    def _boom(_s: str, _u: str) -> str:
        raise RuntimeError("network down")

    set_llm_chat(_boom)
    # fail-open = 入参原样返回；生产漏斗里入参已是规则层处理结果，
    # 所以「还钱吧」先过规则层（→环钱吧）再进 LLM 层，炸了也不丢规则收益。
    assert llm_polyphone_disambiguate(apply_polyphone_substitutions("还钱吧")) == "环钱吧"
    assert llm_polyphone_disambiguate(apply_polyphone_substitutions("还是不行")) == "还是不行"


def test_llm_garbage_falls_back() -> None:
    set_llm_chat(lambda _s, _u: "这不是JSON")
    assert llm_polyphone_disambiguate("还是不行") == "还是不行"
