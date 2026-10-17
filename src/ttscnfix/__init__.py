# -*- coding: utf-8 -*-
"""ttscnfix——中文 TTS 多音字/数字读法修正漏斗（edge-tts / qwen-tts 实跑判例沉淀）。"""
from .polyphone import (
    POLYPHONE_RULES,
    POLYPHONE_WATCH_CHARS,
    PINYIN_SUBSTITUTES,
    apply_polyphone_substitutions,
    llm_polyphone_disambiguate,
    normalize_arabic_numerals,
    set_llm_chat,
    uncovered_arabic_digits,
    uncovered_polyphone_hits,
    warn_uncovered_watch,
)

__version__ = "0.1.0"

__all__ = [
    "POLYPHONE_RULES",
    "POLYPHONE_WATCH_CHARS",
    "PINYIN_SUBSTITUTES",
    "apply_polyphone_substitutions",
    "llm_polyphone_disambiguate",
    "normalize_arabic_numerals",
    "set_llm_chat",
    "uncovered_arabic_digits",
    "uncovered_polyphone_hits",
    "warn_uncovered_watch",
    "__version__",
]


def fix(text: str) -> str:
    """一行接入：数字归一化 → 确定性多音字规则 → 可选 LLM 消歧（生产漏斗顺序）。"""
    return llm_polyphone_disambiguate(apply_polyphone_substitutions(normalize_arabic_numerals(text)))
