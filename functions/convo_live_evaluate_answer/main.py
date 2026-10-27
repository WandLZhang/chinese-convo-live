import functions_framework
from flask import jsonify, request
from google.cloud import firestore
import google.auth
import google.auth.transport.requests
import requests
import os
from datetime import datetime, timezone
import json
from google.protobuf.timestamp_pb2 import Timestamp

import srs

# Initialize clients
db = firestore.Client()

# --- Grading LLM: Gemini 3.5 Flash-Lite (Vertex OpenAI-compatible endpoint), the fastest model serving on
# 2026-10-18 (~0.8s per grade). It replaced Grok, which Vertex stopped serving (grok-4.1-fast 404, then
# grok-4.20-non-reasoning 503). Grading = assess (fluent, meaningful_usage) + feedback + a natural reply. ---
_creds, _adc_project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
LLM_PROJECT = os.getenv('PROJECT_ID') or _adc_project  # deploy project; no hardcoded id
GRADE_MODEL = "google/gemini-3.5-flash-lite"
_LLM_URL = (f"https://aiplatform.googleapis.com/v1/projects/{LLM_PROJECT}"
             "/locations/global/endpoints/openapi/chat/completions")


def _llm_grade(system_prompt: str, user_content: str) -> dict:
    """Force a JSON grading object from GRADE_MODEL (OpenAI-compatible Vertex endpoint)."""
    _creds.refresh(google.auth.transport.requests.Request())
    resp = requests.post(_LLM_URL, timeout=60,
        headers={"Authorization": f"Bearer {_creds.token}", "Content-Type": "application/json"},
        json={"model": GRADE_MODEL, "temperature": 0, "max_tokens": 600,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": system_prompt},
                           {"role": "user", "content": user_content}]})
    if resp.status_code != 200:
        raise RuntimeError(f"{GRADE_MODEL} returned {resp.status_code}: {resp.text}")
    return json.loads(resp.json()["choices"][0]["message"]["content"])

def grade_answer(user_answer: str, vocab_word: str, language: str, vocab_entry: dict, generated_question: str = None, requires_alternative: bool = False, target_word: str = None) -> dict:
    """Use GRADE_MODEL to evaluate the answer and provide feedback.

    Args:
        requires_alternative: from generate_question — whether a colloquial alternative was used
        target_word: from generate_question — the actual word used in the question
    """
    
    print(f"\n=== Evaluation Request ===")
    print(f"Language: {language}")
    print(f"Vocabulary Word: {vocab_word}")
    print(f"User Answer: {user_answer}")
    print(f"Requires Alternative (from generate_vocab_question): {requires_alternative}")
    print(f"Target Word (from generate_vocab_question): {target_word}")
    
    # The client always sends target_word (derived from the precomputed `alt`, or the word itself);
    # default to the word defensively so the prompt never references a None target.
    target_word = target_word or vocab_word
    
    # Use generated question if provided, otherwise fall back to entry
    question = generated_question if generated_question else vocab_entry.get(language.lower(), '')
    
    system_prompt = f"""You are a relaxed {language} conversation partner grading a learner's spoken reply
to this question: "{question}". Grade it like a friendly chat, NOT an exam.

A reply is GOOD as long as ALL of these hold:
  - it uses the target word/expression '{target_word}' correctly and meaningfully;
  - the grammar is okay (a native speaker would understand it and find it natural enough);
  - it is at least loosely related to the topic.
It does NOT need to fully or directly answer the question — a related, grammatical reply that uses the
word is exactly what a normal conversation is. Don't penalize short, casual, or tangential replies, and
never require the reply to "answer" anything.

Return ONLY a JSON object with these fields:
{{
  "fluent": <boolean>,           // true if the GRAMMAR is okay (no real grammatical errors)
  "meaningful_usage": <boolean>, // true if '{target_word}' is used correctly and meaningfully
  "improved_answer": <string>,   // a NATURAL reply a real person would actually say in this chat, using
                                 // '{target_word}'. Make it sound like real speech — do NOT restate or
                                 // echo the question back.
  "feedback": <string>           // Priority: (1) if '{target_word}' is missing or misused, briefly tell
                                 // them to work it in; else (2) if there is a GRAMMAR MISTAKE, give ONE
                                 // short, specific English correction naming what's wrong and the fix
                                 // (this is the pedagogical point); else (3) a brief encouraging note
                                 // (<=8 words). English only, one sentence, no markdown. Do NOT nag
                                 // about "not answering the question" or length.
}}
{f"Cantonese note: '{target_word}' is the spoken form to check — judge natural expression of the meaning." if requires_alternative else ""}"""

    user_content = (f'Question asked: "{question}"\n'
                    f"Target word the reply should use: {target_word}\n"
                    f'Learner\'s reply: "{user_answer}"\n\nGrade it now. JSON only.')
    try:
        print(f"\n=== Sending grading request to {GRADE_MODEL} ===")
        evaluation = _llm_grade(system_prompt, user_content)
        print("\n=== Parsed Evaluation ===")
        print(json.dumps(evaluation, indent=2, ensure_ascii=False))
        return evaluation
    except Exception as e:
        print(f"\n=== Evaluation Error ===")
        print(f"Error: {str(e)}")
        raise

def current_card(raw: dict, language: str) -> dict:
    """The word's SRS card for this language: stored, legacy (scheduled by the old fixed-interval
    code, so a due time but no card), or new."""
    card = raw.get(f'srs{language.capitalize()}')
    if isinstance(card, dict):
        return card
    if raw.get(f'nextReview{language.capitalize()}') is not None:
        return srs.legacy_card()
    return srs.new_card()


@functions_framework.http
def evaluate_answer(request):
    print("\n====== New Evaluation Request ======")
    
    # CORS headers
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)

    headers = {'Access-Control-Allow-Origin': '*'}

    try:
        request_json = request.get_json()
        print("\n=== Request Parameters ===")
        print(f"Request JSON: {json.dumps(request_json, indent=2)}")
        
        doc_id = request_json.get('docId')
        language = request_json.get('language')
        user_answer = request_json.get('answer')
        had_difficulty = request_json.get('hadDifficulty', False)
        
        # Get the vocabulary document
        print("\n=== Fetching Vocabulary Document ===")
        doc_ref = db.collection('vocabulary').document(doc_id)
        doc = doc_ref.get()
        if not doc.exists:
            print(f"Document not found: {doc_id}")
            return (jsonify({'error': 'Document not found'}), 404, headers)
        
        raw = doc.to_dict()
        next_review_field = f'nextReview{language.capitalize()}'
        srs_field = f'srs{language.capitalize()}'
        due_before = raw.get(next_review_field)  # aware UTC datetime, or None
        card = current_card(raw, language)

        vocab_data = dict(raw)
        # Convert Firestore timestamps to ISO format strings
        timestamp_fields = ['timestamp', 'nextReviewMandarin', 'nextReviewCantonese']
        for field in timestamp_fields:
            if field in vocab_data and vocab_data[field]:
                vocab_data[field] = vocab_data[field].isoformat() if hasattr(vocab_data[field], 'isoformat') else None
        # default=str: the srs maps hold a datetime (`last`) that json can't encode on its own.
        print(f"Vocabulary Data: {json.dumps(vocab_data, indent=2, default=str, ensure_ascii=False)}")
        
        # Get the generated question and new parameters from the request
        generated_question = request_json.get('generatedQuestion')
        requires_alternative = request_json.get('requiresAlternative', False)  # NEW: from generate_vocab_question
        target_word = request_json.get('targetWord')  # NEW: from generate_vocab_question
        
        print(f"\n=== Values from generate_vocab_question ===")
        print(f"requiresAlternative: {requires_alternative}")
        print(f"targetWord: {target_word}")
        
        # Evaluate the answer
        evaluation = grade_answer(
            user_answer,
            vocab_data['simplified'],
            language,
            vocab_data,
            generated_question,
            requires_alternative,  # NEW: pass through
            target_word  # NEW: pass through
        )
        
        # Schedule it the way Anki would (srs.py: SM-2, default deck options).
        now = datetime.now(timezone.utc)
        grade = srs.grade_from(evaluation, had_difficulty)
        new_card, next_review = srs.schedule(card, grade, now, due_before)
        print("\n=== Scheduling ===")
        print(json.dumps({'grade': grade, 'had_difficulty': had_difficulty, 'due_before': due_before,
                          'card_before': card, 'card_after': new_card, 'next_review': next_review},
                         indent=2, default=str, ensure_ascii=False))

        doc_ref.update({next_review_field: next_review, srs_field: new_card})

        timestamp = Timestamp()
        timestamp.FromDatetime(next_review)

        response = {
            'success': True,
            'evaluation': evaluation,
            'grade': grade,
            'nextReview': {
                'seconds': timestamp.seconds,
                'nanoseconds': timestamp.nanos
            },
        }
        
        return (jsonify(response), 200, headers)

    except Exception as e:
        print(f'\n=== Error Processing Request ===')
        print(f'Error: {str(e)}')
        print(f'Error Type: {type(e).__name__}')
        import traceback
        print(f'Traceback:\n{traceback.format_exc()}')
        return (jsonify({'error': str(e)}), 500, headers)

@functions_framework.http
def update_review_time(request):
    """Endpoint to update review time after manual adjustment"""
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)

    headers = {'Access-Control-Allow-Origin': '*'}

    try:
        request_json = request.get_json()
        print(f"Request JSON: {json.dumps(request_json, ensure_ascii=False)}")
        doc_id = request_json.get('docId')
        language = request_json.get('language')
        new_review_time = request_json.get('newReviewTime')
        learning = bool(request_json.get('learning', False))

        if not all([doc_id, language, new_review_time]):
            return (jsonify({'error': 'Missing required fields'}), 400, headers)

        # Parse the ISO string and preserve exact time. The client sends UTC without an offset.
        review_time = datetime.fromisoformat(new_review_time)
        if review_time.tzinfo is None:
            review_time = review_time.replace(tzinfo=timezone.utc)

        doc_ref = db.collection('vocabulary').document(doc_id)
        next_review_field = f'nextReview{language.capitalize()}'
        update = {next_review_field: review_time}
        # learning=True (drawer "Schedule" and "Unmark") puts the word into learning step 0, so it
        # comes up at the front of the queue when it falls due. Without it (the date picker) only the
        # due time changes, like Anki's "Set due date".
        if learning:
            srs_field = f'srs{language.capitalize()}'
            snap = doc_ref.get()
            existing = (snap.to_dict() or {}).get(srs_field) if snap.exists else None
            update[srs_field] = srs.learning_card(existing if isinstance(existing, dict) else None)
        print(f"Update: {json.dumps(update, default=str, ensure_ascii=False)}")
        doc_ref.update(update)

        # Convert datetime to Timestamp for response
        timestamp = Timestamp()
        timestamp.FromDatetime(review_time)
        print(f"\n=== Time Values ===")
        print(f"Input ISO string: {new_review_time}")
        print(f"Parsed datetime: {review_time}")
        print(f"Timestamp: seconds={timestamp.seconds}, nanos={timestamp.nanos}")
        
        return (jsonify({
            'success': True,
            'nextReview': {
                'seconds': timestamp.seconds,
                'nanoseconds': timestamp.nanos
            }
        }), 200, headers)

    except Exception as e:
        print(f'Error updating review time: {str(e)}')
        return (jsonify({'error': str(e)}), 500, headers)
