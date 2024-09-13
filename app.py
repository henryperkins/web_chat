# app.py

from datetime import datetime
import json
from flask import Flask, session, jsonify, request, render_template
from werkzeug.utils import secure_filename
from flask_session import Session
from flask_socketio import SocketIO, emit
import os
import logging
import requests
from bson import json_util
import uuid
from pymongo import MongoClient, ASCENDING, DESCENDING, TEXT
from dotenv import load_dotenv
from utils import (
    allowed_file,
    file_size_under_limit,
    handle_file_chunks,
    generate_conversation_text
)

# Load environment variables
load_dotenv()

# Flask app initialization
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default_secret_key')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
Session(app)

# Initialize MongoDB client
MONGODB_URI = os.getenv('MONGODB_URI')
mongo_client = MongoClient(MONGODB_URI)
db = mongo_client['chatbot_db']
conversations_collection = db['conversations']
AZURE_API_URL = os.getenv('AZURE_API_URL')
API_KEY = os.getenv('API_KEY')
MAX_TOKENS = int(os.getenv('MAX_TOKENS', 128000))
REPLY_TOKENS = int(os.getenv('REPLY_TOKENS', 800))
CHUNK_SIZE_TOKENS = int(os.getenv('CHUNK_SIZE_TOKENS', 1000))
# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize SocketIO with Eventlet
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Validation schema (ensure this matches your actual schema)
validation_schema = {
    '$jsonSchema': {
        'bsonType': 'object',
        'required': ['conversation_id', 'user_id', 'conversation_history', 'created_at'],
        'properties': {
            'conversation_id': {'bsonType': 'string'},
            'user_id': {'bsonType': 'string'},
            'conversation_history': {
                'bsonType': 'array',
                'items': {
                    'bsonType': 'object',
                    'required': ['role', 'content'],
                    'properties': {
                        'role': {'enum': ['user', 'assistant']},
                        'content': {'bsonType': 'string'}
                    }
                }
            },
            'conversation_text': {'bsonType': 'string'},
            'created_at': {'bsonType': 'date'},
            'updated_at': {'bsonType': 'date'}
        }
    }
}

def initialize_db():
    try:
        # Apply validation schema
        db.create_collection('conversations', validator=validation_schema)
        logging.info("Collection 'conversations' created with schema validation.")
    except Exception as e:
        if 'already exists' in str(e):
            db.command('collMod', 'conversations', validator=validation_schema)
            logging.info("Schema validation applied to existing 'conversations' collection.")
        else:
            logging.error(f"Error creating collection with validation: {e}")

    # Create indexes
    conversations_collection.create_index(
        [('conversation_text', TEXT)],
        name='conversation_text_index',
        default_language='english'
    )
    logging.info("Text index created on 'conversation_text' field.")

    conversations_collection.create_index(
        [('conversation_id', ASCENDING), ('user_id', ASCENDING)],
        name='conversation_user_idx',
        unique=True
    )
    logging.info("Unique index created on 'conversation_id' and 'user_id' fields.")

    conversations_collection.create_index(
        [('created_at', DESCENDING)],
        name='created_at_idx'
    )
    logging.info("Index created on 'created_at' field.")

# Initialize the database
initialize_db()

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
    conversation_text = ''
    created_at = datetime.utcnow()

    # Save to MongoDB
    conversations_collection.insert_one({
        'conversation_id': conversation_id,
        'user_id': user_id,
        'conversation_history': conversation_history,
        'conversation_text': conversation_text,
        'created_at': created_at,
        'updated_at': created_at
    })

    return jsonify({"message": "New conversation started.", "conversation_id": conversation_id}), 200

@app.route('/reset_conversation', methods=['POST'])
def reset_conversation():
    """Resets the ongoing conversation by clearing the stored conversation history."""
    try:
        conversation_id = session.get('conversation_id')
        user_id = session.get('user_id', 'anonymous')

        if not conversation_id:
            return jsonify({"message": "No active conversation to reset."}), 400

        # Reset conversation in MongoDB
        conversations_collection.update_one(
            {'conversation_id': conversation_id, 'user_id': user_id},
            {'$set': {
                'conversation_history': [],
                'conversation_text': '',
                'updated_at': datetime.utcnow()
            }}
        )
        return jsonify({"message": "Conversation has been reset successfully!"}), 200
    except Exception as e:
        logging.error(f"Error resetting conversation: {str(e)}")
        return jsonify({"message": "An error occurred resetting the conversation", "error": str(e)}), 500

@app.route('/list_conversations', methods=['GET'])
def list_conversations():
    """Lists all conversations for the current user."""
    user_id = session.get('user_id', 'anonymous')
    conversations = conversations_collection.find(
        {'user_id': user_id},
        {'_id': 0, 'conversation_id': 1, 'created_at': 1}
    ).sort('created_at', DESCENDING)
    conversation_list = list(conversations)
    return jsonify({"conversations": conversation_list}), 200

@app.route('/load_conversation/<conversation_id>', methods=['GET'])
def load_conversation(conversation_id):
    """Loads a conversation by ID."""
    user_id = session.get('user_id', 'anonymous')
    conversation = conversations_collection.find_one(
        {'conversation_id': conversation_id, 'user_id': user_id},
        {'_id': 0}
    )
    if conversation:
        session['conversation_id'] = conversation_id
        return jsonify({"conversation": conversation['conversation_history']}), 200
    else:
        return jsonify({"message": "Conversation not found."}), 404

@app.route('/save_history', methods=['POST'])
def save_history():
    """Saves the current conversation history to a JSON file."""
    conversation_id = session.get('conversation_id')
    user_id = session.get('user_id', 'anonymous')

    if not conversation_id:
        return jsonify({"message": "No active conversation to save."}), 400

    conversation = conversations_collection.find_one(
        {'conversation_id': conversation_id, 'user_id': user_id},
        {'_id': 0}
    )

    if not conversation:
        return jsonify({"message": "Conversation not found."}), 404

    # Use a timestamp for unique filenames
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file_name = f'{timestamp}_{conversation_id}_conversation_history.json'

    try:
        os.makedirs('saved_conversations', exist_ok=True)  # Ensure directory exists
        with open(os.path.join('saved_conversations', file_name), 'w') as outfile:
            json.dump(conversation, outfile, default=json_util.default)
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
    results = conversations_collection.find(
        {
            'user_id': user_id,
            '$text': {'$search': query}
        },
        {
            'conversation_id': 1,
            'created_at': 1,
            'updated_at': 1,
            'score': {'$meta': 'textScore'}
        }
    ).sort([('score', {'$meta': 'textScore'})])

    conversations = []
    for conv in results:
        conversations.append({
            'conversation_id': conv['conversation_id'],
            'created_at': conv['created_at'].isoformat(),
            'updated_at': conv.get('updated_at', '').isoformat(),
            'score': conv['score']
        })

    return jsonify({"conversations": conversations}), 200

@app.route('/add_few_shot_example', methods=['POST'])
def add_few_shot_example():
    """Adds few-shot examples to the ongoing conversation."""
    data = request.json
    user_prompt = data.get("user_prompt")
    assistant_response = data.get("assistant_response")

    if not user_prompt or not assistant_response:
        return jsonify({"message": "Both 'user_prompt' and 'assistant_response' are required."}), 400

    conversation_id = session.get('conversation_id')
    user_id = session.get('user_id', 'anonymous')

    if not conversation_id:
        return jsonify({"message": "No active conversation. Please start a new conversation."}), 400

    # Load conversation from MongoDB
    conversation = conversations_collection.find_one(
        {'conversation_id': conversation_id, 'user_id': user_id}
    )

    if not conversation:
        return jsonify({"message": "Conversation not found."}), 404

    conversation_history = conversation['conversation_history']
    conversation_history.extend([
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": assistant_response}
    ])

    # Update conversation_text
    conversation_text = generate_conversation_text(conversation_history)
    updated_at = datetime.utcnow()

    # Save updated conversation
    conversations_collection.update_one(
        {'conversation_id': conversation_id, 'user_id': user_id},
        {'$set': {
            'conversation_history': conversation_history,
            'conversation_text': conversation_text,
            'updated_at': updated_at
        }}
    )

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

    # Add user's message to conversation history
    conversation_history.append({"role": "user", "content": user_message})

    # Manage token limits
    conversation_history, total_tokens_used = manage_token_limits(conversation_history)
    emit('token_usage', {'total_tokens_used': total_tokens_used})

    # Prepare payload for API request
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
            # Add assistant's response to conversation history
            conversation_history.append({"role": "assistant", "content": assistant_response})

            # Update conversation_text
            conversation_text = generate_conversation_text(conversation_history)
            updated_at = datetime.utcnow()

            # Save updated conversation
            conversations_collection.update_one(
                {'conversation_id': conversation_id, 'user_id': user_id},
                {'$set': {
                    'conversation_history': conversation_history,
                    'conversation_text': conversation_text,
                    'updated_at': updated_at
                }}
            )

            # Send the assistant's response to the client
            emit('response_chunk', {'chunk': assistant_response})
        else:
            emit('error', {'message': "No valid response from the API"})

    except requests.RequestException as request_error:
        logging.error(f"Failed to communicate with API: {str(request_error)}")
        emit('error', {'message': f"Failed to communicate with API: {str(request_error)}"})

@app.route('/get_config')
def get_config():
    """Returns configuration data like MAX_TOKENS."""
    return jsonify({"max_tokens": MAX_TOKENS}), 200

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
        return jsonify({"message": "File too large. Max size is 5MB"}), 400

    try:
        file_content = file.read().decode('utf-8')
        _, full_analysis_result = handle_file_chunks(file_content)
        logging.info(f"File uploaded and analyzed successfully: {filename}")
        return jsonify({"message": "File was uploaded and analyzed successfully.", "analysis": full_analysis_result}), 200
    except Exception as e:
        logging.error(f"Error uploading or analyzing file: {str(e)}")
        return jsonify({"message": f"An error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    # Launch the Flask app with SocketIO enabled using Eventlet
    socketio.run(app, debug=True, port=5000)
