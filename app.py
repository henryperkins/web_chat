from flask import Flask, session, jsonify, request, render_template
from flask_session import Session
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
import os
import json
from datetime import datetime, timedelta
from redis import Redis, ConnectionError
import requests
import logging
from pymongo import MongoClient  # Import MongoClient
import uuid
from utils import count_tokens, manage_token_limits, allowed_file, file_size_under_limit, handle_file_chunks, analyze_chunk_with_llama

# Ensure the saved_conversations directory exists
SAVED_CONVERSATIONS_DIR = './saved_conversations'
os.makedirs(SAVED_CONVERSATIONS_DIR, exist_ok=True)

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__, static_url_path='', static_folder='static', template_folder='templates')

# Updated Redis configuration with error handling
try:
    # Setup Redis server for session management
    redis_server = Redis(host='localhost', port=6379)
    # Test the Redis connection
    redis_server.ping()
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_REDIS'] = redis_server
except ConnectionError as e:
    # Gracefully handle Redis connection failure
    logging.warning(f"Redis server is not reachable. Falling back to filesystem. Error: {str(e)}")
    app.config.pop('SESSION_REDIS', None)  # Remove Redis config
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_COOKIE_NAME'] = 'my_app_session'

# Configure logging
logging.basicConfig(level=logging.INFO)

# Securely obtain configuration variables
AZURE_API_URL = os.getenv('AZURE_API_URL')
API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY', 'default_secret_key')
MONGODB_URI = os.getenv('MONGODB_URI')
MAX_TOKENS = int(os.getenv('MAX_TOKENS', 32000))
REPLY_TOKENS = int(os.getenv('REPLY_TOKENS', 1000))

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

# Initialize MongoDB client
mongo_client = MongoClient(MONGODB_URI)
db = mongo_client['chatbot_db']
conversations_collection = db['conversations']

# Set secret key for session
app.secret_key = SECRET_KEY

# Initialize session
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
Session(app)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

@app.route('/')
def index():
    """Serve the main page of the application."""
    return render_template('index.html')

@app.route('/start_conversation', methods=['POST'])
def start_conversation():
    """Starts a new conversation and assigns a unique conversation ID."""
    conversation_id = str(uuid.uuid4())
    session['conversation_id'] = conversation_id
    user_id = session.get('user_id', 'anonymous')

    # Initialize empty conversation history
    conversation_history = []

    # Save to MongoDB
    conversations_collection.insert_one({
        'conversation_id': conversation_id,
        'user_id': user_id,
        'conversation_history': conversation_history,
        'created_at': datetime.utcnow()
    })

    return jsonify({"message": "New conversation started.", "conversation_id": conversation_id}), 200

###
### @app.route('/reset_conversation', methods=['POST'])
def reset_conversation():
    """Resets the ongoing conversation by clearing the stored conversation history within the user's session."""
    try:
        session.pop('conversation', None)
        return jsonify({"message": "Conversation has been reset successfully!"}), 200
    except Exception as e:
        logging.error(f"Error resetting conversation: {str(e)}")
        return jsonify({"message": "An error occurred resetting the conversation", "error": str(e)}), 500
###
###
@app.route('/list_conversations', methods=['GET'])
def list_conversations():
    """Lists all conversations for the current user."""
    user_id = session.get('user_id', 'anonymous')
    conversations = conversations_collection.find({'user_id': user_id}, {'_id': 0, 'conversation_id': 1, 'created_at': 1})
    conversation_list = list(conversations)
    return jsonify({"conversations": conversation_list}), 200

@app.route('/load_conversation/<conversation_id>', methods=['GET'])
def load_conversation(conversation_id):
    """Loads a conversation by ID."""
    user_id = session.get('user_id', 'anonymous')
    conversation = conversations_collection.find_one({'conversation_id': conversation_id, 'user_id': user_id})
    if conversation:
        session['conversation_id'] = conversation_id
        return jsonify({"conversation": conversation['conversation_history']}), 200
    else:
        return jsonify({"message": "Conversation not found."}), 404

@app.route('/save_history', methods=['POST'])
def save_history():
    """Saves the current conversation history to a JSON file."""
    conversation = session.get('conversation', [])
    if not conversation:
        return jsonify({"message": "No conversation to save"}), 400

    # Use a user-friendly timestamp for unique filenames or UUID
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file_name = f'{timestamp}_conversation_history.json'

    try:
        with open(os.path.join(SAVED_CONVERSATIONS_DIR, file_name), 'w') as outfile:
            json.dump(conversation, outfile)
        logging.info(f"Conversation saved successfully: {file_name}")
        return jsonify({"message": "Conversation history saved successfully."}), 200
    except Exception as e:
        logging.error(f"Error saving conversation: {str(e)}")
        return jsonify({"message": f"Failed to save conversation: {str(e)}"}), 500

@app.route('/search_conversations', methods=['GET'])
def search_conversations():
    """Searches across all conversations for the current user."""
    query = request.args.get('q')
    user_id = session.get('user_id', 'anonymous')

    if not query:
        return jsonify({"message": "No search query provided."}), 400

    # Perform text search
    conversations = conversations_collection.find(
        {
            'user_id': user_id,
            '$text': {'$search': query}
        },
        {'_id': 0, 'conversation_id': 1, 'conversation_history': 1}
    )

    conversation_list = list(conversations)
    return jsonify({"conversations": conversation_list}), 200

@app.route('/add_few_shot_example', methods=['POST'])
def add_few_shot_example():
    """Adds few-shot examples to the ongoing conversation stored in the session."""
    data = request.json
    user_prompt = data.get("user_prompt")
    assistant_response = data.get("assistant_response")

    if not user_prompt or not assistant_response:
        return jsonify({"message": "Both 'user_prompt' and 'assistant_response' are required."}), 400

    if 'conversation' not in session:
        session['conversation'] = []

    session['conversation'].extend([
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": assistant_response}
    ])

    logging.info("Few-shot example added successfully")
    return jsonify({"message": "Few-shot example added successfully!"}), 200

@socketio.on('send_message')
def handle_message(data):
    """Handles incoming messages via WebSocket."""
    user_message = data.get('message')
    conversation_id = session.get('conversation_id')
    user_id = session.get('user_id', 'anonymous')

    if not user_message:
        emit('error', {'message': 'No message received from user.'})
        return

    if not conversation_id:
        emit('error', {'message': 'No active conversation. Please start a new conversation.'})
        return

    # Load conversation history from MongoDB
    conversation = conversations_collection.find_one({'conversation_id': conversation_id, 'user_id': user_id})
    if conversation:
        conversation_history = conversation['conversation_history']
    else:
        conversation_history = []

    # Manage token limits
    conversation_history, total_tokens_used = manage_token_limits(conversation_history, user_message)
    conversations_collection.update_one(
        {'conversation_id': conversation_id, 'user_id': user_id},
        {'$set': {'conversation_history': conversation_history}}
    )

    emit('token_usage', {'total_tokens_used': total_tokens_used})

    payload = {
        'messages': conversation_history,
        'max_tokens': REPLY_TOKENS,
        'temperature': 0.7,
        'top_p': 0.95
    }

    try:
        response = requests.post(AZURE_API_URL, headers=HEADERS, json=payload)
        response.raise_for_status()
        response_data = response.json()

        assistant_response = response_data.get('choices', [{}])[0].get('message', {}).get('content', '')

        if assistant_response:
            # Update conversation history
            conversation_history.append({"role": "assistant", "content": assistant_response})
            conversations_collection.update_one(
                {'conversation_id': conversation_id, 'user_id': user_id},
                {'$set': {'conversation_history': conversation_history}}
            )
            emit('response_chunk', {'chunk': assistant_response})
        else:
            emit('error', {'message': "No valid response from the API"})

    except requests.RequestException as request_error:
        logging.error(f"Failed to communicate with API: {str(request_error)}")
        emit('error', {'message': f"Failed to communicate with API: {str(request_error)}"})

@app.route('/get_config')
def get_config():
    """Returns configuration data like MAX_TOKENS."""
    return jsonify({"max_tokens": MAX_TOKENS})

@app.route('/upload_file', methods=['POST'])
def upload_file():
    """Handles file uploads, validates and processes files."""
    if 'file' not in request.files or request.files['file'].filename == '':
        return jsonify({"message": "No file selected."}), 400

    file = request.files['file']
    filename = secure_filename(file.filename)

    if not allowed_file(filename):
        return jsonify({"message": "Unsupported file type."}), 400

    if not file_size_under_limit(file):
        return jsonify({"message": "File too large. Max size is 10MB"}), 400

    try:
        file_content = file.read().decode('utf-8')
        _, full_analysis_result = handle_file_chunks(file_content)
        logging.info(f"File uploaded and analyzed successfully: {filename}")
        return jsonify({"message": "File was uploaded and analyzed successfully.", "analysis": full_analysis_result}), 200
    except Exception as e:
        logging.error(f"Error uploading or analyzing file: {str(e)}")
        return jsonify({"message": f"An error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    # Launch the Flask app with SocketIO enabled
    socketio.run(app, debug=True, port=5000)  # Adjust port as necessary