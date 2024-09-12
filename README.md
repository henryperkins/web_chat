# Llama Chatbot with Token Streaming and File Uploads

## Overview

This project is a chatbot solution that integrates with Azure's Meta Llama 3.1 language model to provide real-time responses to user input. The system allows for **real-time token streaming** via WebSockets, **session management** using Redis, and supports **file uploads** for analysis. It also tracks token usage during the conversation and provides a user-friendly frontend interface.

### Features

- **Real-Time Chat**: Users can engage in real-time conversations with the Llama 3.1 model, with tokenized responses streamed back in chunks.
- **Token Usage Tracking**: Keeps track of how many tokens the user’s current conversation has used.
- **File Uploads**: Upload text files (`.txt`, `.md`, `.json`) for analysis and processing by the Llama model.
- **Few-Shot Learning Support**: Add training examples to guide the model's responses.
- **Conversation History**: Save and load previous conversations.
- **Session Management**: Redis-backed sessions ensure persistent conversation history.

---

## Setup and Installation

### Prerequisites

This application requires the following to be installed:

- **Python 3.7+**
- **Flask**
- **Flask-SocketIO**
- **Azure OpenAI Client**
- **requests**
- **json**
- **os**
- **Redis** (for session storage)
- **Redis-Py** (Redis client in Python required for session)

### Step 1: Clone the Repository

```bash
git clone https://github.com/your-username/llama-chatbot.git
cd llama-chatbot
```

### Step 2: Install Dependencies

Make sure you have `pip` installed, then install the required dependencies:

```bash
pip install -r requirements.txt
```

Or, if you are using `Pipenv`:

```bash
pipenv install
```

### Step 3: Set Up Redis

You need a running **Redis** server to store session data:

- Install and start Redis on Linux/Mac:

  ```bash
  sudo apt-get install redis-server
  sudo service redis-server start
  ```

- On Mac using Homebrew:

  ```bash
  brew install redis
  brew services start redis
  ```

- On Windows: You can install Redis via [Redis for Windows](https://github.com/MicrosoftArchive/redis/releases).

Make sure your Redis server is up and running (`redis-server`).

### Step 4: Environment Variables

Set up the necessary **environment variables** to authenticate the Llama 3.1 API model. Example:

- **API Key**: `MxFB1fUJ8HAKfX9mWEvVc9IxbtKOcN4Q`
- **Azure Endpoint**: `https://Meta-Llama-3-1-405B-Instruct-egb.eastus.models.ai.azure.com/v1/chat/completions`

```bash
export AZURE_API_URL="<your_api_url>"
export API_KEY="<your_api_key>"
```

### Step 5: Running the Application

From your project folder, run the Flask application:

```bash
python3 app.py
```

By default, the app will be running on `http://127.0.0.1:5000/`.

---

## Usage

### Real-time Chat Interaction

Users can interact with the chatbot by opening the client in their browser, sending input messages, and receiving real-time responses.

### Token Usage

The **Token Usage** counter at the bottom of the interface keeps track of total tokens used in the user's current conversation.

### Uploading Files for Analysis

Support for file uploads is provided under acceptable constraints (text files up to 5MB). The bot will divide large files into tokenized chunks and analyze them incrementally.

---

## Features Breakdown

1. **Chat Real-time Token Streaming**:
   - Responses are streamed incrementally from the server to the user in chunks.
   - Users see replies as they are generated, allowing for near-instant interaction.

2. **File Uploads**:
   - Files can be uploaded, and their contents will be analyzed chunk-by-chunk by the backend.
   - Supported formats: `.txt`, `.md`, `.json`.

3. **Few-shot Examples**:
   - Users can add few-shot learning inputs to fine-tune Llama's responses.

4. **Backend Token Management**:
   - The backend ensures that the total token count of a conversation is managed properly, trimming older messages to fit inside Llama's token limit.

---

## Routes & APIs

### Chat Routes

- `/reset_conversation`: Resets the current conversation, clears stored history.
- `/save_history`: Saves the current conversation to a file.
- `/list_conversations`: Lists saved conversations on the server.
- `/load_conversation/<filename>`: Loads a previously saved conversation.

### WebSocket Events

- `send_message`: Sends a message, and streams tokens back chunk by chunk.
- `response_chunk`: Emits each chunk of tokenized response.
- `token_usage`: Tracks the token usage for the conversation.

### File Upload Route

- `/upload_file`: Uploads `.txt`, `.md`, or `.json` files for chunked analysis.

---

### Additional Notes

- Ensure Redis is running for session management.
- Restart both the Flask server and Redis if you experience any issues.
