import functions_framework
from flask import jsonify, request
from google.cloud import firestore
import logging

# Initialize Firestore client
db = firestore.Client()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@functions_framework.http
def mark_word_mastered(request):
    """HTTP Cloud Function to mark a word as mastered in a specific language."""
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
        doc_id = request_json.get('docId')
        language = request_json.get('language')
        
        logger.info(f'Received request to mark word {doc_id} as mastered for {language}')
        
        if not all([doc_id, language]):
            logger.error('Missing required fields')
            return (jsonify({'error': 'Missing required fields'}), 400, headers)
        
        # Get the document first to verify it exists
        doc_ref = db.collection('vocabulary').document(doc_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            logger.error(f'Document {doc_id} not found')
            return (jsonify({'error': 'Document not found'}), 404, headers)
        
        # Update the document
        mastered_field = f'mastered_{language}'
        next_review_field = f'nextReview{language.capitalize()}'
        
        # Get mastered state from request, default to True for backward compatibility
        mastered = request_json.get('mastered', True)
        
        update_data = {
            mastered_field: mastered,
        }
        
        # Only remove review time when marking as mastered
        if mastered:
            update_data[next_review_field] = None
        
        doc_ref.update(update_data)
        logger.info(f'Successfully marked word {doc_id} as mastered for {language}')

        return (jsonify({
            'success': True,
            'message': f'Word marked as mastered for {language}'
        }), 200, headers)

    except Exception as e:
        logger.error(f'Error marking word as mastered: {str(e)}')
        return (jsonify({'error': str(e)}), 500, headers)
