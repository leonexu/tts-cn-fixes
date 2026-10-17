# -*- coding: utf-8 -*-
"""生成 examples/before_after 音频对照样例（须能直连 edge-tts 服务的网络）。

用法：python examples/make_samples.py
产出：examples/before_after/{01,02}_{before,after}.mp3
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import edge_tts  # noqa: E402

from ttscnfix import fix  # noqa: E402

VOICE = "zh-CN-YunxiNeural"
OUT = Path(__file__).resolve().parent / "before_after"

PAIRS = [
    # 病灶1：一行代码（xíng→háng）+ 数字逐位读（10→一零）
    ("我写了三年代码，最忙的一周，一行代码都没写，因为10年没碰技术了。", "01"),
    # 病灶2：同行（tóngxíng→tóng háng）+ 命令行 + 行情
    ("认识了很多同行，大家都说用命令行操作，看行情再决定。", "02"),
]


async def synth(text: str, out: Path) -> None:
    await edge_tts.Communicate(text, VOICE).save(str(out))


async def main() -> int:
    OUT.mkdir(exist_ok=True)
    for raw, idx in PAIRS:
        fixed = fix(raw)
        print(f"[{idx}] raw   : {raw}")
        print(f"[{idx}] fixed : {fixed}")
        await synth(raw, OUT / f"{idx}_before.mp3")
        await synth(fixed, OUT / f"{idx}_after.mp3")
    print("done ->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
