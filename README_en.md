# ttscnfix · Chinese TTS pronunciation fixes (polyphones & numerals)

中文说明见 [README.md](./README.md)。

Fixes the two most common mispronunciations of Chinese neural TTS voices
(edge-tts, qwen-tts, ...) with **zero dependencies and deterministic rules**:

- **Polyphones**: 「一行代码」(yī háng code) read as yī *xíng* → fixed to be read correctly
- **Digit-by-digit numerals**: 「10年」read as *yī líng nián* → fixed to *shí nián*

**How it works**: edge-tts has no SSML/pinyin support, so the only reliable fix is
rewriting the **TTS input text**: swap error-prone characters with same-sound
same-tone homophones, and convert Arabic numerals to Chinese quantity readings
(years / model IDs / IPs are auto-exempted). Your UI/subtitles keep showing the
original text.

```python
from ttscnfix import fix

tts_input = fix("我写了三年代码，一行代码都没写，10年没碰技术了。")
# -> 我写了三年代码，一航代码都没写，十年没碰技术了。
```

The rule table is distilled from real production misreads (each rule carries its
provenance in comments). Optional LLM disambiguation covers the reverse-direction
gaps of the regex rules — plug in any synchronous chat callable via
`set_llm_chat`; everything fails open to the deterministic result.

```bash
pip install git+https://github.com/leonexu/tts-cn-fixes.git
echo "我写了三年代码，一行代码都没写" | ttscnfix
```

MIT license. Bug reports welcome as issues: original text → what the engine read → expected reading.
