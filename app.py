from flask import Flask, session, jsonify, request, render_template
from flask_session import Session
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
import os
import json
from datetime import datetime, timedelta
from redis import Redis, ConnectionError
import requests
from dotenv import load_dotenv
import logging

# Import the consolidated utility functions
from utils import count_tokens, manage_token_limits, allowed_file, file_size_under_limit, handle_file_chunks, analyze_chunk_with_llama

app = Flask(__name__, static_url_path='', static_folder='static', template_folder='templates')

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Load environment variables from a .env file
load_dotenv()

# Securely obtain API keys and URLs from the environment
AZURE_API_URL = os.getenv('AZURE_API_URL')
API_KEY = os.getenv('API_KEY')
MAX_TOKENS = int(os.getenv('MAX_TOKENS', 32000))
REPLY_TOKENS = int(os.getenv('REPLY_TOKENS', 1000))

HEADERS = {
    "Content-Type": "application/json",
    "api-key": API_KEY,
    "Authorization": f"Bearer {API_KEY}"  # Add Authorization header
}

# Ensure the saved_conversations directory exists
SAVED_CONVERSATIONS_DIR = './saved_conversations'
os.makedirs(SAVED_CONVERSATIONS_DIR, exist_ok=True)

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
    logging.warning(f"Redis server is not reachable. Session management will fall back to filesystem. Error: {str(e)}")
    app.config['SESSION_TYPE'] = 'filesystem'  # Fallback to filesystem session storage or another solution
    app.config['SESSION_PERMANENT'] = True         # Make sessions non-permanent by default
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)  # Sessions last for 30 minutes
    app.config['SESSION_USE_SIGNER'] = True         # Sign the session ID for added security
    app.config['SESSION_KEY_PREFIX'] = 'sess:'      # Prefix for session keys in Redis
    app.config['SESSION_COOKIE_NAME'] = 'my_app_session'  # Name of the session cookie

# Set a secret key for securely signing the session cookies
app.secret_key = 'your_secret_key'

# Initialize session extension
Session(app)

# Initialize SocketIO for real-time WebSocket communication
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

@app.route('/')
def index():
    """
    Serve the main page of the application.
    """
    return render_template('index.html')

@app.route('/reset_conversation', methods=['POST'])
def reset_conversation():
    """
    Resets the ongoing conversation by clearing the stored conversation history
    within the user's session.

    Returns:
        Success message in JSON format indicating the conversation has been reset.
    """
    try:
        # Reset only conversation-related session data
        session.pop('conversation', None)
        return jsonify({"message": "Conversation has been reset successfully!"}), 200

    except Exception as e:
        logging.error(f"Error resetting conversation: {str(e)}")
        return jsonify({"message": "An error occurred resetting the conversation", "error": str(e)}), 500

@app.route('/list_conversations', methods=['GET'])
def list_conversations():
    try:
        if not os.path.exists(SAVED_CONVERSATIONS_DIR):
            logging.warning(f"Directory {SAVED_CONVERSATIONS_DIR} does not exist.")
            return jsonify({"conversations": []}), 200

        files = os.listdir(SAVED_CONVERSATIONS_DIR)
        conversation_files = [file for file in files if file.endswith('.json')]
        logging.info(f"Found {len(conversation_files)} conversation files.")
        return jsonify({"conversations": conversation_files}), 200

    except Exception as e:
        logging.error(f"Error listing conversations: {str(e)}")
        return jsonify({"message": f"Failed to list conversations: {str(e)}"}), 500

@app.route('/save_history', methods=['POST'])
def save_history():
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

@app.route('/load_conversation/<filename>', methods=['GET'])
def load_conversation(filename):
    """
    Loads a saved conversation from a JSON file on the server.
    This is useful for restoring past conversations when a user continues an interrupted chat session.

    Returns the conversation (in JSON) and repopulates it back into the session storage for continuity.
    """
    try:
        file_path = os.path.join(SAVED_CONVERSATIONS_DIR, filename)
        if not os.path.exists(file_path):
            return jsonify({"message": f"Conversation file {filename} not found"}), 404

        with open(file_path, 'r') as file:
            conversation_history = json.load(file)

        # Repopulate session with loaded conversation
        session['conversation'] = conversation_history

        logging.info(f"Conversation loaded successfully: {filename}")
        return jsonify({"conversation": conversation_history}), 200
    except Exception as e:
        logging.error(f"Error loading conversation: {str(e)}")
        return jsonify({"message": "Error loading conversation", "error": str(e)}), 500

@app.route('/add_few_shot_example', methods=['POST'])
def add_few_shot_example():
    """
    Adds few-shot examples to the ongoing conversation stored in the session.
    Few-shot learning is a technique that informs the model by providing specific examples
    of how it should respond in future conversations, improving its responsiveness/accuracy.

    The function parses the user's prompt and the desired model (assistant) response and appends
    those to the conversation history.
    """
    data = request.json
    user_prompt = data.get("user_prompt")
    assistant_response = data.get("assistant_response")

    if not user_prompt or not assistant_response:
        return jsonify({"message": "Both 'user_prompt' and 'assistant_response' are required."}), 400

    # Ensure conversation session exists
    if 'conversation' not in session:
        session['conversation'] = []

    # Append few-shot examples to the conversation
    session['conversation'].extend([
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": assistant_response}
    ])

    logging.info("Few-shot example added successfully")
    return jsonify({"message": "Few-shot example added successfully!"}), 200

@socketio.on('send_message')
def handle_message(data):
    user_message = data.get('message')

    if not user_message:
        emit('error', {'message': 'No message received from user.'})
        return

    if 'conversation' not in session:
        session['conversation'] = []

    conversation_history, total_tokens_used = manage_token_limits(session['conversation'], user_message)

    emit('token_usage', {'total_tokens_used': total_tokens_used})

    conversation_history.append({"role": "user", "content": user_message})

    payload = {
        'messages': conversation_history,
        'max_tokens': REPLY_TOKENS,
        'temperature': 0.7,
        'top_p': 0.95,
        'frequency_penalty': 0,
        'presence_penalty': 0,
        'stop': None
    }

    try:
        response = requests.post(AZURE_API_URL, headers=HEADERS, json=payload)
        response.raise_for_status()
        response_data = response.json()

        if 'choices' in response_data and len(response_data['choices']) > 0:
            assistant_response = response_data['choices'][0]['message']['content']
            conversation_history.append({"role": "assistant", "content": assistant_response})
            session['conversation'] = conversation_history

            # Emit the full response
            emit('response_chunk', {'chunk': assistant_response})

            _, final_token_usage = manage_token_limits(conversation_history)
            emit('token_usage', {'total_tokens_used': final_token_usage})
        else:
            emit('error', {'message': "No valid response from the API"})

    except requests.RequestException as request_error:
        logging.error(f"Failed to communicate with Llama API: {str(request_error)}")
        emit('error', {'message': f"Failed to communicate with Llama API: {str(request_error)}"})

    except Exception as general_error:
        logging.error(f"An unexpected error occurred: {str(general_error)}")
        emit('error', {'message': f"An unexpected error occurred: {str(general_error)}"})

@app.route('/upload_file', methods=['POST'])
def upload_file():
    if 'file' not in request.files or request.files['file'].filename == '':
        return jsonify({"message": "No file selected."}), 400

    file = request.files['file']

    if not allowed_file(file.filename):
        return jsonify({"message": "Unsupported file type."}), 400

    if not file_size_under_limit(file):
        return jsonify({"message": "File too large. Max size is 10MB"}), 400

    try:
        file_content = file.read().decode('utf-8')
        _, full_analysis_result = handle_file_chunks(file_content)

        logging.info(f"File uploaded and analyzed successfully: {file.filename}")
        return jsonify({ "message": "File was uploaded and analyzed successfully.", "analysis": full_analysis_result }), 200

    except Exception as e:
        logging.error(f"Error uploading or analyzing file: {str(e)}")
        return jsonify({"message": f"An error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    # Launch the Flask app with SocketIO enabled
    socketio.run(app, debug=True, port=5000)  # Adjust port as necessary