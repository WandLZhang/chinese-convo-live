"""
convo_live_generate_question — chinese-convo-live question generator.

Design (locked): the colloquial-alternative decision is PRE-COMPUTED into Firestore as `alt`
(see audit/). So at request time there is NO rule-sifting and NO RAG:
  - alt present  -> write a natural question using the colloquial word `alt` (meaning anchored
                   by the formal `word`), validated + retried so `alt` actually appears.
  - alt absent   -> write a natural question using `word` directly.
Output is the raw question text, streamed (Claude tokens) for the direct case; the alt case is
generated whole (so it can be validated) then emitted. The client already knows word/alt from
the Firestore doc, so no JSON metadata is returned — just the text.

Model: Claude Sonnet 5 on Vertex (AnthropicVertex SDK) — benchmark-selected for the most authentic
colloquial Cantonese/Mandarin (natural word usage + register; e.g. 雪糕 not 冰淇淋, 擔保 in its real
vouch sense); TTFT ~0.6s streamed. Swap GEN_MODEL to change (a Grok/MaaS model would instead need
the OpenAI-compatible endpoint path).
"""
import datetime
import json
import logging
import os
import traceback

import functions_framework
import google.auth
import opencc
from anthropic import AnthropicVertex
from flask import Response, jsonify, stream_with_context

# Force our own INFO handler: importing the anthropic SDK configures root logging, which makes a
# later logging.basicConfig a no-op and silently suppresses our INFO payload/output logs. An
# explicit handler guarantees the word/prompt/FINAL lines reach Cloud Logging (stderr).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.INFO)
    logger.addHandler(_handler)
logger.propagate = False

# Project = the deploy project (from ADC), overridable via PROJECT_ID — no project id is
# hardcoded. This is where Claude (Vertex) is billed and served.
_, _adc_project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
LLM_PROJECT = os.getenv("PROJECT_ID") or _adc_project
GEN_MODEL = "claude-sonnet-5"  # benchmark-selected: most authentic colloquial Cantonese/Mandarin
_client = AnthropicVertex(region="global", project_id=LLM_PROJECT)

# Sonnet 5 emits a thinking block on EVERY call (~120-190 tokens) before the sentence, so a tight
# budget truncates mid-sentence — worst on awkward-to-place words (查获 thought ~185 tokens and got
# cut at the old value of 200). Streaming means unused budget costs nothing. Exported so the
# benchmark imports the SAME value as production (bench/prod drift is what hid the truncation bug).
MAX_TOKENS = 1200

CORS = {"Access-Control-Allow-Origin": "*"}
STREAM_HEADERS = {**CORS, "X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
LANG = {"cantonese": "廣東話", "mandarin": "普通話"}
converter = opencc.OpenCC("s2t")  # simplified -> traditional (Cantonese output must be traditional)


def _month_day(iso_date):
    """'2026-11-23' -> (11, 23); None when absent or malformed."""
    try:
        d = datetime.date.fromisoformat(str(iso_date))
        return d.month, d.day
    except ValueError:
        return None


# The app each kind of entry came from, as the prompt names it: (Mandarin, Cantonese). Texts and email get their
# own wording below.
APPS = {"signal": ("Signal", "Signal"), "whatsapp": ("WhatsApp", "WhatsApp"), "messenger": ("Messenger", "Messenger"),
        "google_chat": ("Google Chat", "Google Chat")}


def quote_block(quote, today, language):
    """A message, as written, with who sent it, where and when: one someone sent the learner, or one the learner
    sent (sender "me", with `to` naming the recipient of a direct message or email).
    `quote` = {source, preview, sender, to, chat (None = direct message), text, sentDate, replyTo, link}."""
    sender = quote.get("sender") or "someone"
    mine = sender == "me"
    to = quote.get("to")
    chat = quote.get("chat")
    sent = _month_day(quote.get("sentDate"))
    now = _month_day(today)
    reply = quote.get("replyTo") or {}
    link = quote.get("link") or {}
    link_text = link.get("title") or link.get("url")
    text = quote.get("text", "")
    source = quote.get("source") or "signal"
    cantonese = language == "cantonese"
    if source == "email":
        if cantonese:
            lines = (["我最近發咗封電郵：", f"收件人：{to or '一個朋友'}"] if mine
                     else ["最近有人發咗封電郵俾我：", f"寄件人：{sender}"])
        else:
            lines = (["我最近发了一封邮件：", f"收件人：{to or '一个朋友'}"] if mine
                     else ["最近有人给我发了一封邮件：", f"发件人：{sender}"])
    else:
        app_m, app_c = APPS.get(source, (source, source))
        if cantonese:
            if source == "messages":
                intro = "我最近發咗個短訊：" if mine else "最近有人發咗個短訊俾我："
            else:
                intro = f"我最近喺{app_c}度發咗條訊息：" if mine else f"最近有人喺{app_c}度發咗條訊息俾我："
            lines = ([intro, f"喺邊度發：{chat}" if chat else f"發咗俾：{to or '一個朋友'}"] if mine
                     else [intro, f"邊個發：{sender}", f"喺邊度發：{chat or '私訊'}"])
        else:
            if source == "messages":
                intro = "我最近发了一条短信：" if mine else "最近有人给我发了一条短信："
            else:
                intro = f"我最近在{app_m}上发了一条消息：" if mine else f"最近有人在{app_m}上给我发了一条消息："
            lines = ([intro, f"发在哪儿：{chat}" if chat else f"发给：{to or '一个朋友'}"] if mine
                     else [intro, f"发消息的人：{sender}", f"在哪儿发的：{chat or '私聊'}"])
    if cantonese:
        if sent:
            lines.append(f"日期：{sent[0]}月{sent[1]}號" + (f"（今日係{now[0]}月{now[1]}號）" if now else ""))
        if reply.get("text"):
            whom = "我" if reply.get("author") == "me" else reply.get("author") or "人哋"
            lines.append(f"呢條係回覆緊{whom}嘅訊息：「{reply['text']}」")
        if link_text:
            lines.append(f"訊息入面分享咗條連結：{link_text}")
        lines.append(f"{'我嘅' if mine else ''}原文：「{text}」")
        if quote.get("preview"):
            lines.append("（呢段係聊天列表嘅預覽，可能唔完整）")
        if "@me" in text:
            lines.append("（原文入面嘅「@me」即係我）")
    else:
        if sent:
            lines.append(f"日期：{sent[0]}月{sent[1]}日" + (f"（今天是{now[0]}月{now[1]}日）" if now else ""))
        if reply.get("text"):
            whom = "我" if reply.get("author") == "me" else reply.get("author") or "别人"
            lines.append(f"这条是在回{whom}的消息：「{reply['text']}」")
        if link_text:
            lines.append(f"消息里分享的链接：{link_text}")
        lines.append(f"{'我的' if mine else ''}原话：「{text}」")
        if quote.get("preview"):
            lines.append("（这是聊天列表里的预览，可能不完整）")
        if "@me" in text:
            lines.append("（原话里的“@me”指的是我）")
    return "\n".join(lines) + "\n"


def build_prompt(word, alt, language, personal_context, conversation_context, quote=None, today=None):
    """One prompt for every turn: weave the SRS word (or its colloquial alt) into a natural,
    idiomatic sentence that fits the learner's life and the recent exchange. Statement or question
    — no '?' required. No turn-type branching; trust the model to connect things naturally.
    `quote` (a Signal message, see quote_block) replaces `personal_context` (a one-line summary from
    the older entries) when present, and the prompt says whose news it is."""
    sender = (quote or {}).get("sender") or "someone"
    mine = sender == "me"
    if language == "cantonese":
        word_t = converter.convert(word)  # traditional so output stays traditional
        target = alt if alt else word_t
        alt_note = f"（口語，即係書面語「{word_t}」）" if alt else ""
        recent = f"我哋啱啱傾緊：\n{conversation_context}\n" if conversation_context else ""
        if quote:
            facts = quote_block(quote, today, language)
            tie = "就算要拗個彎都要扣返呢條訊息同啱啱傾嘅嘢（陳述句或問句都得）。" + (
                "呢條訊息係我自己發嘅。" if mine else
                f"訊息係{sender}講嘅，提起嗰陣要講清楚係邊個講、邊個做，唔好將人哋嘅事當咗係我嘅。")
        else:
            facts = f"我嘅近況：\n{personal_context}\n" if personal_context else ""
            tie = "就算要拗個彎都要扣返我嘅近況同啱啱傾嘅嘢（陳述句或問句都得）。"
        prompt = (f"你幫緊我練廣東話。{recent}{facts}"
                  f"寫一句你想問我或者同我講嘅、自然又地道嘅口語廣東話，句入面一定要用到「{target}」{alt_note}，"
                  f"{tie}淨係輸出嗰句，用繁體字，唔要jyutping、翻譯或者解釋。")
    else:
        target = word
        recent = f"我们刚在聊：\n{conversation_context}\n" if conversation_context else ""
        if quote:
            facts = quote_block(quote, today, language)
            tie = "就算要绕个弯也要扣上这条消息和刚聊的内容（陈述句或问句都行）。" + (
                "这条消息是我自己发的。" if mine else
                f"消息是{sender}发的，提到的时候要说清楚是谁说的、谁做的，别把别人的事安到我头上。")
        else:
            facts = f"我的近况：\n{personal_context}\n" if personal_context else ""
            tie = "就算要绕个弯也要扣上我的近况和刚聊的内容（陈述句或问句都行）。"
        prompt = (f"你在帮我练普通话。{recent}{facts}"
                  f"写一句你想问我或者跟我说的、自然又地道的口语普通话，句子里一定要用到「{word}」，"
                  f"{tie}只输出那一句，不要拼音、翻译或者解释。")
    return prompt, target


def _claude_full(system, nudge, max_tokens):
    """Whole (non-streamed) generation — used by the alt path so the output can be validated."""
    msg = _client.messages.create(model=GEN_MODEL, max_tokens=max_tokens, system=system,
                                  messages=[{"role": "user", "content": nudge}])
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()


def _claude_stream(system, nudge, max_tokens):
    """Token stream for the direct path (natural typewriter UX)."""
    with _client.messages.stream(model=GEN_MODEL, max_tokens=max_tokens, system=system,
                                 messages=[{"role": "user", "content": nudge}]) as stream:
        for text in stream.text_stream:
            yield text


@functions_framework.http
def convo_live_generate_question(request):
    if request.method == "OPTIONS":
        return ("", 204, {**CORS, "Access-Control-Allow-Methods": "POST",
                          "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "3600"})
    try:
        req = request.get_json(silent=True) or {}
        logger.info(f"====== convo_live_generate_question ======\n{json.dumps(req, ensure_ascii=False)}")
        word = req.get("word")
        language = req.get("language", "cantonese")
        if not word:
            return (jsonify({"error": "word required"}), 400, CORS)
        alt = (req.get("alt") or "").strip() or None
        personal_context = (req.get("personalContext") or "").strip()
        conversation_context = (req.get("conversationContext") or "").strip()
        # A Signal message as written (entries saved since 2026-11-23); older entries send only the summary.
        quote = req.get("contextQuote")
        quote = quote if isinstance(quote, dict) and (quote.get("text") or "").strip() else None
        system, target = build_prompt(word, alt, language, personal_context, conversation_context,
                                      quote=quote, today=req.get("today"))
        max_tokens = MAX_TOKENS
        nudge = "開始。" if language == "cantonese" else "开始。"
        logger.info(f"word={word} alt={alt} language={language} target={target} "
                    f"pcLen={len(personal_context)} quote={'yes' if quote else 'no'} "
                    f"ccLen={len(conversation_context)}")
        logger.info(f"SYSTEM PROMPT:\n{system}")

        # ALT path: must actually contain `alt` -> generate whole, validate, retry, then emit.
        if alt and language == "cantonese":
            text = ""
            for attempt in range(2):  # 1 retry max — a word the model won't produce won't appear on retry either
                text = _claude_full(system, nudge, max_tokens)
                logger.info(f"alt-gen attempt {attempt}: {text}")
                if alt in text:
                    break
            else:
                logger.warning(f"alt '{alt}' not reproduced after retries for word '{word}'; emitting best effort")
            logger.info(f"FINAL (alt path): {text}")

            def gen_alt():
                yield text
            return Response(stream_with_context(gen_alt()), mimetype="text/plain; charset=utf-8",
                            headers=STREAM_HEADERS)

        # DIRECT path: real token streaming.
        def gen_stream():
            collected = []
            try:
                for delta in _claude_stream(system, nudge, max_tokens):
                    collected.append(delta)
                    yield delta
            finally:
                logger.info(f"FINAL (stream path): {''.join(collected)}")
        return Response(stream_with_context(gen_stream()), mimetype="text/plain; charset=utf-8",
                        headers=STREAM_HEADERS)
    except Exception as e:  # noqa: BLE001
        logger.error(f"error: {e}\n{traceback.format_exc()}")
        return (jsonify({"error": str(e)}), 500, CORS)
