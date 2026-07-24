import functions_framework
from flask import jsonify, request
from google.cloud import firestore
import google.auth
import google.auth.transport.requests
import requests
import os
from datetime import datetime, timedelta
import json
from google.protobuf.timestamp_pb2 import Timestamp

# Initialize clients
db = firestore.Client()

# --- Grading LLM: Grok 4.1 Fast — benchmark-selected (100% fluent/meaningful agreement, ~1.1s;
# vs Sonnet 92%/4.7s). Grading = assess (fluent, meaningful_usage) + feedback + a natural reply. ---
_creds, _adc_project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
LLM_PROJECT = os.getenv('PROJECT_ID') or _adc_project  # deploy project; no hardcoded id
GRADE_MODEL = "xai/grok-4.1-fast-non-reasoning"
_GROK_URL = (f"https://aiplatform.googleapis.com/v1/projects/{LLM_PROJECT}"
             "/locations/global/endpoints/openapi/chat/completions")


def _grok_grade(system_prompt: str, user_content: str) -> dict:
    """Force a JSON grading object from Grok (OpenAI-compatible Vertex endpoint)."""
    _creds.refresh(google.auth.transport.requests.Request())
    resp = requests.post(_GROK_URL, timeout=60,
        headers={"Authorization": f"Bearer {_creds.token}", "Content-Type": "application/json"},
        json={"model": GRADE_MODEL, "temperature": 0, "max_tokens": 600,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": system_prompt},
                           {"role": "user", "content": user_content}]})
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

# Scheduling intervals in minutes
INTERVALS = {
    "DIFFICULTY": {
        "IMMEDIATE": 5,      # For had_difficulty=True
        "SHORT": 15,        # For non-fluent usage
        "MEDIUM": 30        # For basic correct usage
    },
    "SUCCESS": {
        "INITIAL": [4320],    # 3d for first success
        "SUBSEQUENT": [21600, 86400]  # 15d, 60d for subsequent successes
    }
}

def grade_answer(user_answer: str, vocab_word: str, language: str, vocab_entry: dict, generated_question: str = None, requires_alternative: bool = False, target_word: str = None) -> dict:
    """Use Grok to evaluate the answer and provide feedback.

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
        print("\n=== Sending grading request to Grok ===")
        evaluation = _grok_grade(system_prompt, user_content)
        print("\n=== Parsed Evaluation ===")
        print(json.dumps(evaluation, indent=2, ensure_ascii=False))
        return evaluation
    except Exception as e:
        print(f"\n=== Evaluation Error ===")
        print(f"Error: {str(e)}")
        raise

def calculate_next_review(
    current_data: dict,
    language: str,
    had_difficulty: bool,
    evaluation: dict,
    now: datetime
) -> datetime:
    """Calculate the next review time based on various factors"""
    
    # For any difficulty or non-fluent usage, use short intervals
    if had_difficulty:
        print("Had difficulty - using IMMEDIATE interval (5 minutes)")
        return now + timedelta(minutes=INTERVALS["DIFFICULTY"]["IMMEDIATE"])
    
    if not evaluation['fluent']:
        print("Not fluent - using SHORT interval (15 minutes)")
        return now + timedelta(minutes=INTERVALS["DIFFICULTY"]["SHORT"])
    
    if not evaluation['meaningful_usage']:
        print("Not meaningful usage - using MEDIUM interval (30 minutes)")
        return now + timedelta(minutes=INTERVALS["DIFFICULTY"]["MEDIUM"])
    
    # For successful, fluent usage
    next_review_field = f'nextReview{language.capitalize()}'
    current_review = current_data.get(next_review_field)
    
    # If this is the first successful review or there was any difficulty recently
    if not current_review or had_difficulty or not evaluation['fluent'] or not evaluation['meaningful_usage']:
        print("First success or recent difficulty - using INITIAL interval (3 days)")
        return now + timedelta(minutes=INTERVALS["SUCCESS"]["INITIAL"][0])
    
    # For subsequent successful reviews
    try:
        # Convert ISO string to datetime if needed
        if isinstance(current_review, str):
            current_review = datetime.fromisoformat(current_review)
        
        # Calculate time difference in minutes
        current_diff = (now - current_review.replace(tzinfo=None)).total_seconds() / 60
        intervals = INTERVALS["SUCCESS"]["INITIAL"] + INTERVALS["SUCCESS"]["SUBSEQUENT"]
        next_interval = next((i for i in intervals if i > current_diff), intervals[-1])
        print(f"Subsequent success - using interval: {next_interval} minutes")
        return now + timedelta(minutes=next_interval)
    except Exception as e:
        print(f"Error calculating interval: {str(e)}, using INITIAL interval")
        return now + timedelta(minutes=INTERVALS["SUCCESS"]["INITIAL"][0])

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
        
        vocab_data = doc.to_dict()
        # Convert Firestore timestamps to ISO format strings
        timestamp_fields = ['timestamp', 'nextReviewMandarin', 'nextReviewCantonese']
        for field in timestamp_fields:
            if field in vocab_data and vocab_data[field]:
                vocab_data[field] = vocab_data[field].isoformat() if hasattr(vocab_data[field], 'isoformat') else None
        print(f"Vocabulary Data: {json.dumps(vocab_data, indent=2)}")
        
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
        
        # Calculate next review time
        now = datetime.utcnow().replace(tzinfo=None)
        print("\n=== Calculating Next Review ===")
        next_review = calculate_next_review(
            vocab_data,
            language,
            had_difficulty,
            evaluation,
            now
        )
        print(f"Next Review Time: {next_review.isoformat()}")
        
        # Update the document with UTC time
        next_review_field = f'nextReview{language.capitalize()}'
        doc_ref.update({
            next_review_field: next_review.replace(tzinfo=None)
        })
        
        # Convert datetime to Timestamp
        timestamp = Timestamp()
        timestamp.FromDatetime(next_review)
        
        # Prepare response with raw timestamp data
        response = {
            'success': True,
            'evaluation': evaluation,
            'nextReview': {
                'seconds': timestamp.seconds,
                'nanoseconds': timestamp.nanos
            },
            'intervals': INTERVALS  # Include available intervals for frontend dropdown
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
        doc_id = request_json.get('docId')
        language = request_json.get('language')
        new_review_time = request_json.get('newReviewTime')
        
        if not all([doc_id, language, new_review_time]):
            return (jsonify({'error': 'Missing required fields'}), 400, headers)
        
        # Parse the ISO string and preserve exact time
        review_time = datetime.fromisoformat(new_review_time)
        
        # Update the document with the exact time
        doc_ref = db.collection('vocabulary').document(doc_id)
        next_review_field = f'nextReview{language.capitalize()}'
        doc_ref.update({
            next_review_field: review_time
        })

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
