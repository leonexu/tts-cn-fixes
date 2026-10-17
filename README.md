# ttscnfix · 中文 TTS 多音字/数字读法修正

[![CI](https://github.com/leonexu/tts-cn-fixes/actions/workflows/ci.yml/badge.svg)](./actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

修中文神经语音（edge-tts / qwen-tts 等）最常翻车的两类读音，**零依赖、纯确定性规则**：

- **多音字读错**：「一行代码」读成「一 xíng 代码」→ 修正后 TTS 读「一 háng 代码」
- **数字逐位读**：「剪片10年」读成「剪片一零年」→ 修正后读「剪片十年」

**原理**：edge-tts 不支持注音/拼音/SSML，唯一的修法是在 **TTS 输入侧**把易错字换成
同音字（含声调）、把数字转成中文数量读法——读音归位，而你的界面/字幕仍显示原始文本。

## 效果对照

| 原文（界面/字幕显示） | 修正后送 TTS | 引擎实际读 |
|---|---|---|
| 一行代码都没写 | 一**航**代码都没写 | yī háng ✓ |
| 认识了很多同行 | 认识了很多同**航** | tóng háng ✓ |
| 搬到国内行不通 | 搬到国内**形**不通 | xíng ✓ |
| 还给他了 | **环**给他了 | huán ✓ |
| 剪片10年 | 剪片**十**年 | shí nián ✓ |
| 98年出生 | **九八**年出生 | jiǔ bā ✓ |
| 转化率2.75% | 转化率**百分之二点七五** | ✓ |
| GPT-4 / 1280x800 / 192.168.1.1 | 原样保留 | ✓ |

（ regenerate 音频对照：`python examples/make_samples.py`，须可直连 edge-tts 的网络）

## 安装

```bash
pip install git+https://github.com/leonexu/tts-cn-fixes.git
```

## 用法

### 一行接入（生产漏斗）

```python
from ttscnfix import fix

text = "我写了三年代码，一行代码都没写，10年没碰技术了。"
tts_input = fix(text)
# -> 我写了三年代码，一航代码都没写，十年没碰技术了。
#    （把 tts_input 送 edge-tts；text 照常显示在字幕里）
```

### 分层使用

```python
from ttscnfix import (
    normalize_arabic_numerals,      # 数字 → 中文数量读法（年份/型号/IP 自动豁免）
    apply_polyphone_substitutions,  # 确定性多音字规则
    llm_polyphone_disambiguate,     # 可选：LLM 上下文消歧（默认关闭）
)

tts_input = llm_polyphone_disambiguate(
    apply_polyphone_substitutions(normalize_arabic_numerals(text))
)
```

### 命令行体验

```bash
echo "我写了三年代码，一行代码都没写" | ttscnfix
```

### 可选：LLM 消歧（管规则表的反向漏判）

确定性规则是「窄正则枚举」，方向单一（huán 义→环），反向漏判（hái 义被引擎读
huán）追不完。接一个 LLM 回调即可泛化：**LLM 只判读音，替身字由本库的拼音→同音
表保证同音同调**；判读没有安全替身就放行原字。无回调/网络异常一律回落规则结果，
不阻塞生产。

```python
from ttscnfix import set_llm_chat, fix

def my_llm_chat(system_prompt: str, user_prompt: str) -> str:
    # 任意同步 LLM 调用（返回原始文本回复即可）
    return my_client.chat(system=system_prompt, user=user_prompt)

set_llm_chat(my_llm_chat)
```

## 规则从哪来

规则表不是词典搬运，是**真实成片误读的判例沉淀**：每条规则来自「成片实拍读错 →
人耳抓到 → 钉死一条窄上下文规则」的闭环，注释保留出处与两条纪律——

1. **上下文必须足够窄**：只在该搭配确实易读错时替换；本来就读对的常见词
   （银行/行业 háng、行动/执行 xíng）不碰。零歧义词（行情/命令行）即使常见也
   确定性入表——实测 LLM 也会把「行情」误判成 xíng。
2. **替换字必须同音同调**：「还 huán」用「环」，不用「换 huàn」——声调不同
   TTS 会读出别扭的四声。

`uncovered_polyphone_hits` / `uncovered_arabic_digits` 两个反查函数用于检测
「文本里的监控多音字/残留数字没有规则覆盖」的场景，提示人工确认，防漏网。

## 贡献

遇到新的误读？欢迎提 issue，格式：**原文 → 引擎实际读成了什么 → 应读什么**。
规则贡献要求窄上下文正则 + 同音同调替换字 + 一个测试用例（`tests/`）。

## License

MIT
