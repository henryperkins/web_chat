import os
import json
from datetime import datetime, timedelta
from flask import session, jsonify, request
from werkzeug.utils import secure_filename
import requests
import tiktoken
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

# Securely obtain API keys and URLs from the environment
AZURE_API_URL = os.getenv('AZURE_API_URL')
API_KEY = os.getenv('API_KEY')
MAX_TOKENS = int(os.getenv('MAX_TOKENS', 128000))  # Convert to int, default to 128000
REPLY_TOKENS = int(os.getenv('REPLY_TOKENS', 800))  # Convert to int, default to 800

# Parse MAX_FILE_SIZE_MB, handling 'm' suffix if present
max_file_size = os.getenv('MAX_FILE_SIZE_MB', '5.0')
if isinstance(max_file_size, str) and max_file_size.lower().endswith('m'):
    MAX_FILE_SIZE_MB = float(max_file_size[:-1])
else:
    MAX_FILE_SIZE_MB = float(max_file_size)

CHUNK_SIZE_TOKENS = int(os.getenv('CHUNK_SIZE_TOKENS', 1000))  # Convert to int, default to 1000
ALLOWED_EXTENSIONS = set(os.getenv('ALLOWED_EXTENSIONS', 'txt,md,json').split(','))

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

# Load Tiktoken-based tokenizer for LLama 3.1
# You need to reference the tokenizer specific to your model or a compatible tokenizer.
encoding = tiktoken.get_encoding("cl100k_base")

def count_tokens(text):
    """
    Count tokens in the text using the Tiktoken-based tokenizer.

    Args:
    text (str): The string of text to tokenize.

    Returns:
    int: The number of tokens in the string.
    """
    return len(encoding.encode(text))

def manage_token_limits(conversation_history, new_message=None):
    """
    Keeps track of tokens ensuring we stay within the limit by removing oldest user messages.
    Also optimizes balance between context history and new messages.
    """
    total_tokens = sum(count_tokens(turn['content']) for turn in conversation_history)

    while total_tokens >= MAX_TOKENS - REPLY_TOKENS:
        turn = conversation_history.pop(0)
        total_tokens -= count_tokens(turn['content'])

    if new_message:
        new_message_tokens = count_tokens(new_message)
        conversation_history.append({"role": "user", "content": new_message})
        total_tokens += new_message_tokens

    return conversation_history, total_tokens

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def file_size_under_limit(file):
    file.seek(0, os.SEEK_END)
    size_bytes = file.tell()
    file_size_mb = size_bytes / (1024 * 1024)
    file.seek(0)
    return file_size_mb <= MAX_FILE_SIZE_MB

def handle_file_chunks(file_content):
    """
    Break file content into smaller tokenized chunks, analyze them via Llama API,
    and gather the model analysis results.

    Args:
        file_content (str): The content of the uploaded file.

    Returns:
        tuple: List of file content chunks and the full analysis result as a string.
    """
    content_chunks = []
    current_chunk = ""
    current_token_count = 0

    # Split content by lines (you could also split by sentences)
    lines = file_content.splitlines()

    # Tokenize and break into manageable chunks
    for line in lines:
        tokens_in_line = count_tokens(line)

        # If adding the line exceeds the CHUNK_SIZE, close current chunk
        if current_token_count + tokens_in_line > CHUNK_SIZE_TOKENS:
            content_chunks.append(current_chunk.strip())  # Add chunk to list
            current_chunk = ""  # Reset chunk
            current_token_count = 0  # Reset token count for new chunk

        current_chunk += line + "\n"
        current_token_count += tokens_in_line

    # Add trailing content as the last chunk
    if current_chunk.strip():
        content_chunks.append(current_chunk.strip())

    # Analyze chunks and gather responses
    full_analysis_result = ""
    for i, chunk in enumerate(content_chunks):
        analysis = analyze_chunk_with_llama(chunk)
        full_analysis_result += f"\n-- Analysis for Chunk {i + 1} --\n{analysis}"

    return content_chunks, full_analysis_result

def analyze_chunk_with_llama(chunk, retries=3):
    """
    Analyzes a text chunk using the Llama API, with added error handling and retries.
    """
    conversation_history = session.get('conversation', [])
    conversation_history.append({"role": "user", "content": chunk})

    payload = {
        "messages": conversation_history,
        "max_tokens": 500,
        "temperature": 0.7
    }

    attempt = 0
    while attempt < retries:
        try:
            response = requests.post(AZURE_API_URL, headers=HEADERS, json=payload)
            response.raise_for_status()
            llama_response = response.json()
            return llama_response['choices'][0]['message']['content']
        except (requests.exceptions.RequestException, KeyError) as e:
            print(f"API error: {e}")
            attempt += 1
            if attempt >= retries:
                return "Unable to process your request at this time. Please try again later."