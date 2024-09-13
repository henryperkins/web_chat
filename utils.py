import os
import json
from flask import session
from datetime import datetime
import requests
import tiktoken
import logging

# Load environment variables from a .env file
from dotenv import load_dotenv
load_dotenv()

# Securely obtain configuration variables
AZURE_API_URL = os.getenv('AZURE_API_URL')
API_KEY = os.getenv('API_KEY')
MAX_TOKENS = int(os.getenv('MAX_TOKENS', 128000))
REPLY_TOKENS = int(os.getenv('REPLY_TOKENS', 800))
CHUNK_SIZE_TOKENS = int(os.getenv('CHUNK_SIZE_TOKENS', 1000))

# Parse MAX_FILE_SIZE_MB
MAX_FILE_SIZE_MB = float(os.getenv('MAX_FILE_SIZE_MB', '5.0').rstrip('m'))

ALLOWED_EXTENSIONS = set(os.getenv('ALLOWED_EXTENSIONS', 'txt,md,json').split(','))

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

# Load tokenizer
encoding = tiktoken.get_encoding("cl100k_base")

def count_tokens(text):
    """Count tokens in the text using the tokenizer."""
    return len(encoding.encode(text))
def generate_conversation_text(conversation_history):
    """
    Generates a text summary of the conversation by concatenating user and assistant messages.
    
    Args:
        conversation_history (list): A list of dictionaries representing the conversation history.
                                     Each dictionary contains 'role' and 'content' keys.
    
    Returns:
        str: A concatenated string representation of the conversation.
    """
    conversation_text = ""
    
    for message in conversation_history:
        role = message.get('role', 'user')
        content = message.get('content', '')
        
        if role == 'user':
            conversation_text += f"User: {content}\n"
        elif role == 'assistant':
            conversation_text += f"Assistant: {content}\n"
    
    return conversation_text.strip()  # Remove any trailing newlines


def summarize_messages(messages, max_summary_tokens=500):
    """Summarizes a list of messages into a shorter text."""
    combined_text = ""
    for msg in messages:
        role = msg['role']
        content = msg['content']
        combined_text += f"{role.capitalize()}: {content}\n"

    prompt = f"Please provide a concise summary of the following conversation:\n{combined_text}\nSummary:"

    payload = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that summarizes conversations."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": max_summary_tokens,
        "temperature": 0.5
    }

    try:
        response = requests.post(AZURE_API_URL, headers=HEADERS, json=payload)
        response.raise_for_status()
        summary_response = response.json()
        summary_content = summary_response['choices'][0]['message']['content'].strip()
        return {"role": "system", "content": f"Summary: {summary_content}"}
    except Exception as e:
        logging.error(f"Error during summarization: {str(e)}")
        return {"role": "system", "content": "Summary not available due to an error."}

def manage_token_limits(conversation_history, new_message=None):
    """Manages the token limits by summarizing older messages when necessary."""
    if new_message:
        temp_history = conversation_history + [{"role": "user", "content": new_message}]
    else:
        temp_history = conversation_history.copy()

    total_tokens = sum(count_tokens(turn['content']) for turn in temp_history)

    if total_tokens >= MAX_TOKENS - REPLY_TOKENS:
        messages_to_summarize = []
        while total_tokens >= MAX_TOKENS - REPLY_TOKENS and len(temp_history) > 1:
            messages_to_summarize.append(temp_history.pop(0))
            total_tokens = sum(count_tokens(turn['content']) for turn in temp_history)

        if messages_to_summarize:
            summary_message = summarize_messages(messages_to_summarize)
            temp_history.insert(0, summary_message)
            total_tokens = sum(count_tokens(turn['content']) for turn in temp_history)

            if total_tokens >= MAX_TOKENS - REPLY_TOKENS:
                return manage_token_limits(temp_history)

    else:
        temp_history = conversation_history.copy()

    if new_message:
        temp_history.append({"role": "user", "content": new_message})
        total_tokens += count_tokens(new_message)

    return temp_history, total_tokens

def allowed_file(filename):
    """Checks if a given file is allowed based on its extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def file_size_under_limit(file):
    """Ensures that the uploaded file size is within the allowed limit."""
    file.seek(0, os.SEEK_END)
    size_bytes = file.tell()
    file_size_mb = size_bytes / (1024 * 1024)
    file.seek(0)
    return file_size_mb <= MAX_FILE_SIZE_MB

def handle_file_chunks(file_content):
    """Break file content into smaller tokenized chunks and analyze them via Llama API."""
    content_chunks = []
    current_chunk = ""
    current_token_count = 0

    lines = file_content.splitlines()

    # Tokenize and break into manageable chunks
    for line in lines:
        tokens_in_line = count_tokens(line)

        if current_token_count + tokens_in_line > CHUNK_SIZE_TOKENS:
            content_chunks.append(current_chunk.strip())  # Add chunk to list
            current_chunk = ""  # Reset chunk
            current_token_count = 0  # Reset token count

        current_chunk += line + "\n"
        current_token_count += tokens_in_line

    # Add trailing content as the last chunk
    if current_chunk.strip():
        content_chunks.append(current_chunk.strip())

    full_analysis_result = ""
    for i, chunk in enumerate(content_chunks):
        analysis = analyze_chunk_with_llama(chunk)
        full_analysis_result += f"\n-- Analysis for Chunk {i + 1} --\n{analysis}"

    return content_chunks, full_analysis_result

def analyze_chunk_with_llama(chunk, retries=3):
    """Analyzes a text chunk using the Llama API, with error handling and retries."""
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