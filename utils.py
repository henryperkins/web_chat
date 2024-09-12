import os
import json
from datetime import datetime, timedelta
from flask import session, jsonify, request
from werkzeug.utils import secure_filename
import requests
import tiktoken

# LLama 3.1 405b Model Configuration
AZURE_API_URL = "https://Meta-Llama-3-1-405B-Instruct-egb.eastus.models.ai.azure.com/v1/chat/completions"
API_KEY = "MxFB1fUJ8HAKfX9mWEvVc9IxbtKOcN4Q"

# Set headers for API requests
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

# Set model limitations: The LLama model has input and output token limits.
# Token limitations & chunk size
MAX_TOKENS = 128000  # model's 128k token limit
CHUNK_SIZE_TOKENS = 120000  # Allowing some buffer below the limit for replies
REPLY_TOKENS = 500  # Maximum tokens for a model reply
ALLOWED_EXTENSIONS = {'txt', 'md', 'json'}
MAX_FILE_SIZE_MB = 5 # Limited the file uploads to 5 MB

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
    Manages token limits by trimming older parts of the conversation and calculates total token usage.

    Args:
        conversation_history (list): List of conversation messages.
        new_message (str): The incoming message to append to the conversation.

    Returns:
        tuple: Updated conversation history limited by tokens, and total token usage.
    """
    total_tokens = 0
    trimmed_conversation = []

    # Traverse existing conversation history
    for turn in conversation_history:
        turn_tokens = count_tokens(turn['content'])
        total_tokens += turn_tokens
        trimmed_conversation.append(turn)

        # Break once the token count exceeds the allowed model limit minus the reply buffer
        if total_tokens >= MAX_TOKENS - REPLY_TOKENS:
            # Remove older messages
            trimmed_conversation.pop(0)

    # Append new user message if available
    if new_message:
        new_message_tokens = count_tokens(new_message)
        trimmed_conversation.append({"role": "user", "content": new_message})
        total_tokens += new_message_tokens

    return trimmed_conversation, total_tokens

def allowed_file(filename):
    """
    Check if the uploaded file has an allowed extension.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def file_size_under_limit(file):
    """
    Check if the file size is under a defined maximum.
    """
    file.seek(0, os.SEEK_END)
    file_size_mb = file.tell() / (1024 * 1024)  # Convert size to megabytes
    file.seek(0)  # Reset file pointer
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

def analyze_chunk_with_llama(chunk):
    """
    Sends a chunk of text to Llama 3.1 for analysis and returns model's response.

    Args:
        chunk (str): The content chunk to be analyzed.

    Returns:
        str: The model's response for the given chunk.
    """
    conversation_history = session.get('conversation', [])

    # Append the chunk as a user message
    conversation_history.append({"role": "user", "content": chunk})

    # Prepare request payload for Llama API
    payload = {
        "messages": conversation_history,
        "max_tokens": 500,  # Limit Llama's response token length
        "temperature": 0.7  # Controls how creative or deterministic the replies are
    }

    try:
        # Send the chunk to Llama model via Azure API
        response = requests.post(AZURE_API_URL, headers=HEADERS, json=payload)
        response.raise_for_status()

        # Parse and return the model's response (assuming JSON response structure)
        llama_response = response.json()
        return llama_response['choices'][0]['message']['content']

    except requests.exceptions.RequestException as e:
        return f"API request failed: {str(e)}"
    except KeyError:
        return "Received invalid response from Llama API."