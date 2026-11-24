#!/opt/venv/bin/python
"""
Signal ingestion (runs on the convo-live-signal VM, hourly via cron).

`signal-cli receive` -> LLM_MODEL screens each message first, both incoming ones and the ones the
owner sends from their phone (sync messages, sender "me"): keep it only if it has enough content to
talk about, and never if it holds credentials, codes or account numbers (a digit backstop runs after
it) or anything personally sensitive: health, intimate life, family conflict, money, legal trouble,
grief, or something said in confidence. A kept message is stored as written in Firestore `context_entries` (source="signal", doc id from
the Signal timestamp) with its sender, recipient, chat, date, the message it replies to and a shared
link's preview. An edit updates the stored copy; a sender's delete-for-everyone deletes it.
A Firestore TTL policy deletes every entry 30 days after `createdAt` (scripts/setup_infra.sh).
Uses the VM's attached SA (convo-live-signal: datastore.user + aiplatform.user).
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess

import google.auth
import google.auth.transport.requests
import requests
from google.cloud import firestore

# cron runs with a bare PATH (/usr/bin:/bin) that omits /usr/local/bin, so resolve signal-cli's
# absolute path here — a bare "signal-cli" raised FileNotFoundError on every cron run.
SIGNAL_CLI = shutil.which("signal-cli") or "/usr/local/bin/signal-cli"
SIGNAL_ACCOUNTS = "/root/.local/share/signal-cli/data/accounts.json"
_creds, _adc_project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
PROJECT = os.getenv("PROJECT_ID") or _adc_project or "your-gcp-project"  # on the VM: derived from ADC
LLM_MODEL = "google/gemini-3.5-flash-lite"
LLM_URL = (f"https://aiplatform.googleapis.com/v1/projects/{PROJECT}"
            "/locations/global/endpoints/openapi/chat/completions")
db = firestore.Client(project=PROJECT)

SCREEN_SYS = (
    "You screen one message that reached the user, or one the user sent (sender \"me\"): a Signal, "
    "WhatsApp, Messenger or text message, a Google Chat message, or an email. A language-learning app "
    "turns each message you keep into a conversation prompt, such as asking the user about what was "
    "said, so keep only messages with enough content to talk about.\n"
    "Keep it when a friend could ask a specific follow-up question about it: news about the sender or "
    "someone they know, a plan or an event, a trip, an opinion, a story, a question with real substance, "
    "an article, newsletter or announcement with something in it to talk about, or a shared link whose "
    "title or description says what it's about. Where it came from doesn't matter: anything that reached "
    "the user counts, newsletters and a business's mail included, as long as it isn't sensitive.\n"
    "Drop it when it's a greeting, thanks or congratulations with no detail; an acknowledgment such as "
    "ok, lol, yes or an emoji; logistics with no story, such as on my way or call me; a bare link with "
    "no title; or a fragment you can't follow without more of the chat.\n"
    "Always drop it, set sensitive to true and name the kind, when the message, the message it replies "
    "to or the link holds any of these:\n"
    "- credential: a password, passcode, PIN, 2FA or one-time code, credential or API key; a financial "
    "account, card, routing or CVV number; an SSN, national ID, passport or driver's license number; or "
    "a full home address.\n"
    "- health: anyone's illness, injury, diagnosis, test result, medication, therapy, mental health, "
    "disability, pregnancy or fertility, including a message that implies one, such as a support group, "
    "clinic, therapist or program someone belongs to.\n"
    "- intimate: sex, dating or an intimate relationship.\n"
    "- conflict: trouble in a marriage or a family, or a child's troubles at school.\n"
    "- money: money trouble or debt, or what the user or someone they know earns or owes.\n"
    "- legal: legal trouble, the police, a lawsuit or immigration status.\n"
    "- grief: a death, a funeral or someone's grief.\n"
    "- confidential: anything said in confidence; work matters that aren't public; a job search, "
    "application, interview or offer of the user or someone they know (news about jobs in general is "
    "fine).\n"
    "Everyday news, plans, trips, opinions, jokes and stories stay eligible.\n"
    "Input fields: source (the app), sender (who sent it; \"me\" is the user), to (who got a direct "
    "message the user sent), chat (the group's name, \"Note to Self\", or null for a direct message), "
    "text (the message; an email's subject is its first line), replyTo (the message it answers; author "
    "\"me\" is the user), link (a shared link's preview), preview (true when text is only a chat-list "
    "preview: it may be cut off, sender is unknown, and chat is the conversation's name). \"@me\" in a "
    "text is the user.\n"
    'Return only a JSON object: {"keep": true or false, "sensitive": true or false, "kind": "the sensitive '
    'kind above, or empty", "reason": "why, in '
    '12 words or fewer", "summary": "if kept, one English sentence of 20 words or fewer naming who said '
    'or did what, calling the user \'the user\'; otherwise empty", "sender": "only when preview is true: '
    'who wrote the text, \\"me\\" for the user (a line starting You:), else the name shown, else the '
    'conversation\'s name"}')


def _token():
    _creds.refresh(google.auth.transport.requests.Request())
    return _creds.token


def screen(item):
    """LLM_MODEL's verdict on one message: {keep, sensitive, reason, summary}."""
    r = requests.post(LLM_URL, timeout=60,
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        json={"model": LLM_MODEL, "temperature": 0, "max_tokens": 300,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": SCREEN_SYS},
                           {"role": "user", "content": json.dumps(item, ensure_ascii=False)}]})
    if r.status_code != 200:
        raise RuntimeError(f"{LLM_MODEL} returned {r.status_code}: {r.text}")
    content = r.json()["choices"][0]["message"].get("content")
    if not content:
        raise RuntimeError(f"{LLM_MODEL} returned no content: {r.text}")
    return json.loads(content)


def _looks_sensitive(text):
    """Deterministic safety net under the LLM screen (not semantic parsing): true if a long digit run
    (card/account/routing, 11+) or an SSN-shaped 3-2-4 group is in the text."""
    groups, cur = [], ""
    for ch in text:
        if ch.isdigit():
            cur += ch
        else:
            if cur:
                groups.append(cur)
                cur = ""
    if cur:
        groups.append(cur)
    if any(len(g) >= 11 for g in groups):
        return True
    return any(len(groups[i]) == 3 and len(groups[i + 1]) == 2 and len(groups[i + 2]) == 4
               for i in range(len(groups) - 2))


def _scannable(item):
    """Every stored text field, with link tokens left out: a URL's long post ID isn't an account number."""
    parts = [item["text"], (item["replyTo"] or {}).get("text") or "",
             (item["link"] or {}).get("title") or "", (item["link"] or {}).get("description") or ""]
    words = " ".join(parts).split()
    return " ".join(w for w in words if "://" not in w)  # a link can sit inside "(...)" or "<...>"


def _accounts():
    """[(number, uuid)] of the linked account(s), from signal-cli's own account file."""
    try:
        with open(SIGNAL_ACCOUNTS) as f:
            return [(a.get("number"), a.get("uuid")) for a in json.load(f).get("accounts", [])]
    except FileNotFoundError:
        return []


def _names(number, accounts):
    """uuid/number -> the contact's name; the linked account itself -> "me"."""
    out = subprocess.run([SIGNAL_CLI, "-a", number, "-o", "json", "listContacts"],
                         capture_output=True, text=True, timeout=120).stdout
    names = {}
    for c in json.loads(out or "[]"):
        prof = c.get("profile") or {}
        name = (c.get("name") or c.get("nickName")
                or " ".join(x for x in (prof.get("givenName"), prof.get("familyName")) if x)).strip()
        for key in (c.get("uuid"), c.get("number")):
            if key and name:
                names[key] = name
    for num, uuid in accounts:
        for key in (num, uuid):
            if key:
                names[key] = "me"
    return names


def _who(names, uuid, number):
    return names.get(uuid) or names.get(number) or "someone"


def _render_mentions(text, mentions, names):
    """Signal puts U+FFFC where an @mention goes; write the person's name there. start and length
    count UTF-16 code units, so splice in UTF-16."""
    if not text or not mentions:
        return text
    u = text.encode("utf-16-le")
    for m in sorted(mentions, key=lambda m: m.get("start", 0), reverse=True):
        s = 2 * m.get("start", 0)
        e = s + 2 * m.get("length", 0)
        u = u[:s] + f"@{_who(names, m.get('uuid'), m.get('number'))}".encode("utf-16-le") + u[e:]
    return u.decode("utf-16-le")


def _item(env, dm, names, sent=None):
    """The message as the app stores it, or None when it has no text (reactions, stickers, photos).
    `sent` is the sync record of a message the owner sent from their phone; it names the recipient."""
    text = _render_mentions(dm.get("message"), dm.get("mentions"), names)
    if not text or not text.strip():
        return None
    group = dm.get("groupInfo")
    chat = (group.get("groupName") or "a group chat") if group else None  # None = direct message
    if sent is not None:
        sender, to = "me", None
        if not group:
            to = _who(names, sent.get("destinationUuid"), sent.get("destinationNumber"))
            if to == "me":
                chat, to = "Note to Self", None
    else:
        sender = env.get("sourceName") or _who(names, env.get("sourceUuid"), env.get("sourceNumber"))
        to = None
    q = dm.get("quote") or {}
    reply = None
    if q.get("text"):
        reply = {"author": _who(names, q.get("authorUuid"), q.get("authorNumber")),
                 "text": _render_mentions(q.get("text"), q.get("mentions"), names)}
    pv = (dm.get("previews") or [{}])[0] or {}
    link = ({"url": pv.get("url"), "title": pv.get("title"), "description": pv.get("description")}
            if pv.get("url") else None)
    return {"source": "signal", "sender": sender, "to": to, "chat": chat, "text": text, "replyTo": reply,
            "link": link}


def _ref(ts):
    return db.collection("context_entries").document(
        "e" + hashlib.sha1(f"signal:{ts}".encode("utf-8")).hexdigest()[:20])


def store(ts, item, verdict):
    """Write a kept message; delete a stored copy that an edit turned into one we drop."""
    keep = verdict.get("keep") is True and verdict.get("sensitive") is not True
    if keep and _looks_sensitive(_scannable(item)):
        keep = False
        verdict["backstop"] = True
    ref = _ref(ts)
    exists = ref.get().exists
    if not keep:
        if exists:
            ref.delete()
            return "deleted"
        return "dropped"
    fields = {"text": verdict.get("summary") or item["text"], "quote": item["text"], "preview": False,
              "sender": item["sender"], "to": item["to"], "chat": item["chat"], "replyTo": item["replyTo"],
              "link": item["link"],
              "sentAt": datetime.datetime.fromtimestamp(int(ts) / 1000, tz=datetime.timezone.utc)}
    if exists:
        ref.update(fields)
        return "updated"
    ref.set({**fields, "source": "signal", "sourceRef": str(ts), "createdAt": firestore.SERVER_TIMESTAMP,
             "usedCantoneseAt": None, "usedMandarinAt": None})
    return "kept"


def main():
    accounts = _accounts()
    if not accounts or not accounts[0][0]:
        print("no linked signal account")
        return
    number = accounts[0][0]
    names = _names(number, accounts)
    out = subprocess.run([SIGNAL_CLI, "-a", number, "-o", "json", "receive"],
                         capture_output=True, text=True, timeout=180).stdout
    counts = {"kept": 0, "updated": 0, "dropped": 0, "deleted": 0, "failed": 0}
    for line in out.splitlines():
        try:
            env = json.loads(line).get("envelope", {})
        except ValueError:
            continue
        sent = (env.get("syncMessage") or {}).get("sentMessage")
        if sent:  # sent from the owner's phone: the data message's fields sit on `sent` itself
            dm, ts, edit = sent, sent.get("timestamp"), sent.get("editMessage")
        else:
            dm, ts, edit = env.get("dataMessage"), env.get("timestamp"), env.get("editMessage")
        if edit:  # an edit replaces the stored copy of the original message
            dm, ts = edit.get("dataMessage"), edit.get("targetSentTimestamp")
        if not dm or not ts:
            continue
        gone = (dm.get("remoteDelete") or {}).get("timestamp")
        if gone:  # the sender deleted it for everyone, so drop our copy too
            ref = _ref(gone)
            if ref.get().exists:
                ref.delete()
                counts["deleted"] += 1
                print(json.dumps({"ref": gone, "action": "deleted", "why": "sender deleted it"}))
            continue
        item = _item(env, dm, names, sent)
        if not item:
            continue
        try:
            verdict = screen(item)
            action = store(ts, item, verdict)
            counts[action] += 1
            if verdict.get("sensitive") is True or verdict.get("backstop"):
                # Never write a sensitive message to the log, not even inside the model's reason; the kind
                # (health, money, ...) is enough to check the screen.
                print(json.dumps({"ref": ts, "action": action, "sensitive": verdict.get("sensitive") is True,
                                  "kind": str(verdict.get("kind") or "")[:20],
                                  "backstop": bool(verdict.get("backstop"))}))
            else:
                print(json.dumps({"ref": ts, "item": item, "verdict": verdict, "action": action},
                                 ensure_ascii=False))
        except Exception as ex:  # noqa: BLE001 — one bad message must not abort the batch
            counts["failed"] += 1
            print(f"signal item {ts} failed: {ex}")
    print(f"signal ingest: {json.dumps(counts)}")


if __name__ == "__main__":
    main()
