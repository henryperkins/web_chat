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

# Import the consolidated utility functions
from utils import count_tokens, manage_token_limits, allowed_file, file_size_under_limit, handle_file_chunks, analyze_chunk_with_llama

app = Flask(__name__, static_url_path='', static_folder='static', template_folder='templates')

# Load environment variables from a .env file
load_dotenv()

# Securely obtain API keys and URLs from the environment
AZURE_API_URL = os.getenv('AZURE_API_URL')
API_KEY = os.getenv('API_KEY')
MAX_TOKENS = os.getenv('MAX_TOKENS')
REPLY_TOKENS = os.getenv('REPLY_TOKENS')

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

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
    print(f"Warning: Redis server is not reachable. Session management will fall back to filesystem.")
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
socketio = SocketIO(app, cors_allowed_origins="*")

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
        return jsonify({"message": "An error occurred resetting the conversation", "error": str(e)}), 500

@app.route('/list_conversations', methods=['GET'])
def list_conversations():
    try:
        # Better practice: save conversation histories in a sub-directory
        files = os.listdir('./saved_conversations')
        conversation_files = [file for file in files if file.endswith('.json')]
        return jsonify({"conversations": conversation_files}), 200

    except Exception as e:
        return jsonify({"message": f"Failed to list conversations: {str(e)}"}), 500

@app.route('/save_history', methods=['POST'])
def save_history():
    conversation = session.get('conversation', [])
    if not conversation:
        return jsonify({"message": "No conversation to save"}), 400

    # Use a user-friendly timestamp for unique filenames or UUID
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file_name = f'{timestamp}_conversation_history.json'

    with open(os.path.join('./saved_conversations', file_name), 'w') as outfile:
        json.dump(conversation, outfile)
    return jsonify({"message": "Conversation history saved successfully."}), 200

@app.route('/load_conversation/<filename>', methods=['GET'])
def load_conversation(filename):
    """
    Loads a saved conversation from a JSON file on the server.
    This is useful for restoring past conversations when a user continues an interrupted chat session.

    Returns the conversation (in JSON) and repopulates it back into the session storage for continuity.
    """
    try:
        with open(filename, 'r') as file:
            conversation_history = json.load(file)

        # Repopulate session with loaded conversation
        session['conversation'] = conversation_history

        return jsonify({"conversation": conversation_history}), 200
    except Exception as e:
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
        'temperature': 0.7
    }

    try:
        response = requests.post(AZURE_API_URL, headers=HEADERS, json=payload, stream=True)
        response.raise_for_status()

        assistant_response = ""

        for token_chunk in response.iter_lines():
            if token_chunk:
                token_chunk = token_chunk.decode('utf-8')
                assistant_response += token_chunk
                emit('response_chunk', {'chunk': token_chunk})

        conversation_history.append({"role": "assistant", "content": assistant_response})
        session['conversation'] = conversation_history

        _, final_token_usage = manage_token_limits(conversation_history)
        emit('token_usage', {'total_tokens_used': final_token_usage})

    except requests.RequestException as request_error:
        emit('error', {'message': f"Failed to communicate with Llama API: {str(request_error)}"})
        print(f"Error: {str(request_error)}")

    except Exception as general_error:
        emit('error', {'message': f"An unexpected error occurred: {str(general_error)}"})
        print(f"General Error: {str(general_error)}")

@app.route('/upload_file', methods=['POST'])
def upload_file():
    if 'file' not in request.files or request.files['file'].filename == '':
        return jsonify({"message": "No file selected."}), 400

    file = request.files['file']

    if not allowed_file(file.filename):
        return jsonify({"message": "Unsupported file type."}), 400

    if not file_size_under_limit(file):
        return jsonify({"message": "File too large. Max size is 5MB"}), 400

    try:
        file_content = file.read().decode('utf-8')
        _, full_analysis_result = handle_file_chunks(file_content)

        return jsonify({ "message": "File was uploaded and analyzed successfully.", "analysis": full_analysis_result }), 200

    except Exception as e:
        return jsonify({"message": f"An error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    # Launch the Flask app with SocketIO enabled
    socketio.run(app, port=5000)  # Adjust port as necessary