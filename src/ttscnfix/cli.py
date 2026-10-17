# -*- coding: utf-8 -*-
"""命令行体验入口：echo 文本 | ttscnfix  或  ttscnfix "文本"。

零依赖零配置——只跑确定性规则（多音字表 + 数字读法）。LLM 消歧走 Python API
（set_llm_chat），CLI 不做任何网络调用。
"""
from __future__ import annotations

import sys

from . import fix


def main() -> int:
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__.strip())
        return 0
    args = [a for a in sys.argv[1:] if a not in ("-h", "--help")]
    if args:
        text = " ".join(args)
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        print(__doc__.strip())
        return 1
    fixed = fix(text.strip())
    if fixed != text.strip():
        print(fixed)
    else:
        print("(无命中规则，原文输出)")
        print(text.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
