// Connect to the Socket.IO backend for WebSocket communication
const socket = io('http://your-backend-domain:5000', {
    transports: ['websocket'],      // Ensure WebSocket is the primary transport
    reconnection: true,             // Enable reconnection attempts
    reconnectionDelay: 1000,        // Reconnect after 1 second
    maxReconnectionAttempts: 5      // Stop reconnecting after 5 attempts
});

/**
 * Sends the user's message to the backend and triggers the AI model to generate a response.
 * The message will be displayed in the chat, and the response will stream as tokens via WebSocket.
 */
function sendMessage() {
    const messageInput = document.getElementById('user-message');
    const message = messageInput.value.trim();

    // Prevent sending empty messages
    if (!message) return;

    // Display the user's message in the chat
    appendMessage('user', message);

    // Send the message to the backend via WebSocket
    socket.emit('send_message', { message: message });

    // Clear the input field after sending
    messageInput.value = '';
}

/**
 * Appends a new message to the chat history.
 * Messages from the user and the assistant will be styled and aligned differently.
 *
 * @param {string} role - 'user' or 'assistant'
 * @param {string} content - The message content
 */
function appendMessage(role, content) {
    const chatHistory = document.getElementById('chat-history');

    // Create a new message element
    const messageElement = document.createElement('div');
    messageElement.classList.add(`${role}-message`);
    messageElement.textContent = content;

    // Append the message to the chat history
    chatHistory.appendChild(messageElement);

    // Auto-scroll to the latest message
    chatHistory.scrollTop = chatHistory.scrollHeight;

    // Call auto-scroll to keep the most recent message in view
    autoScroll();
}

// Listen for token chunks streamed back from the server in real time
socket.on('response_chunk', data => {
    appendMessage('assistant', data.chunk);
});

// Handle error cases and display error messages to the user
socket.on('error', data => {
    console.error(data.message);
    showAlert('Error: ' + data.message, 'error');
});

// Listen for updates on total token usage coming from the backend
socket.on('token_usage', data => {
    updateTokenUsage(data.total_tokens_used);
});

/**
 * Update the UI to display the current token usage.
 *
 * @param {number} tokens - The number of tokens currently used in the conversation.
 */
function updateTokenUsage(tokens) {
    const tokenUsageElement = document.getElementById('token-usage');

    if (tokenUsageElement) {
        tokenUsageElement.textContent = `Token Usage: ${tokens}`;
    }
}
/**
 * Resets the entire conversation by clearing out both the frontend and backend conversation history.
 * This will remove all messages from the chat and reset state.
 */
async function resetConversation() {
    const resetButton = document.querySelector('button[onclick="resetConversation()"]');
    resetButton.disabled = true;  // Disable the button to prevent double-action
    resetButton.textContent = "Resetting...";  // Show loading text or spinner

    const response = await fetch('/reset_conversation', { method: 'POST' });
    const data = await response.json();

    // Clear conversation history in the UI
    document.getElementById('chat-history').innerHTML = '';

    // Notify the user that the conversation has been reset
    showAlert(data.message, 'success');

    resetButton.disabled = false;       // Re-enable the button
    resetButton.textContent = "Reset Conversation";  // Restore button's original text
}

/**
 * Saves the current conversation history to the backend.
 * The user will be notified after the conversation has been successfully saved.
 */
async function saveConversation() {
    const response = await fetch('/save_history', { method: 'POST' });
    const data = await response.json();
    showAlert(data.message, 'success');

    // Refresh the list of saved conversations after save
    listConversations();
}

/**
 * Fetches and displays a list of all previously saved conversations from the backend.
 * Each conversation in the list provides options for loading or downloading.
 */
let conversationCache = null;
let cacheTimestamp = null;

async function listConversations(forceRefresh = false) {
    const cacheValidDuration = 60 * 1000;  // Cache validity: 1 minute

    // Check if we have cached the list recently
    const cacheExpired = !cacheTimestamp || (Date.now() - cacheTimestamp) > cacheValidDuration;

    if (!forceRefresh && conversationCache && !cacheExpired) {
        renderConversations(conversationCache);
        return;
    }

    // Fetch from server if cache is missing or expired
    try {
        const response = await fetch('/list_conversations');
        const data = await response.json();

        conversationCache = data.conversations;  // Cache the list
        cacheTimestamp = Date.now();             // Save the time of fetching

        renderConversations(conversationCache);  // Render the list to DOM
    } catch (error) {
        console.error("Error fetching conversations:", error);
        showAlert('Error fetching saved conversations. Please try again.', 'error');
    }
}

function renderConversations(conversations) {
    const conversationList = document.getElementById('conversation-list');
    conversationList.innerHTML = '';  // Clear existing content

    if (conversations.length === 0) {
        conversationList.innerHTML = '<li>No conversations saved.</li>';  // Empty state
    } else {
        conversations.forEach(filename => {
            const listItem = document.createElement('li');
            listItem.innerHTML = `
                ${filename}
                <button onclick="loadConversation('${filename}')">Load</button>
                <a href="/download_conversation/${filename}" download>Download</a>
            `;
            conversationList.appendChild(listItem);
        });
    }
}
/**
 * Loads a previously saved conversation from the backend and repopulates the chat history with the messages.
 *
 * @param {string} filename - The name of the conversation file to load.
 */
async function loadConversation(filename) {
    const response = await fetch(`/load_conversation/${filename}`);
    const data = await response.json();

    if (!response.ok) {
        showAlert('Error: Unable to load conversation', 'error');
        return;
    }

    const chatHistory = document.getElementById('chat-history');
    chatHistory.innerHTML = '';  // Clear existing chat history

    // Append each message from the loaded conversation
    data.conversation.forEach(entry => {
        appendMessage(entry.role, entry.content);
    });

    showAlert(`Loaded conversation: ${filename}`, 'success');
}

/**
 * Adds a few-shot example consisting of a user prompt and assistant response to the running conversation.
 * Both pieces are sent to the backend and saved as part of the conversation context.
 */
async function addFewShotExample() {
    const userPrompt = document.getElementById('user-prompt').value;
    const assistantResponse = document.getElementById('assistant-response').value;

    if (!userPrompt || !assistantResponse) {
        showAlert('User prompt and assistant response are required fields.', 'error');
        return;
    }

    const response = await fetch('/get_conversation');  // API to get the current conversation
    const data = await response.json();

    let isDuplicate = false;
    if (data && data.conversation) {
        // Search for an existing user prompt in the current conversation
        isDuplicate = data.conversation.some(
            turn => turn.role === 'user' && turn.content === userPrompt
        );
    }

    if (isDuplicate) {
        showAlert('This few-shot example already exists in the conversation.', 'error');
        return;
    }

    // Proceed with sending the new few-shot example to the backend
    const res = await fetch('/add_few_shot_example', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            user_prompt: userPrompt,
            assistant_response: assistantResponse
        })
    });

    const result = await res.json();
    showAlert(result.message, 'success');

    // Clear input fields post submission
    document.getElementById('user-prompt').value = '';
    document.getElementById('assistant-response').value = '';
}

/**
 * Handles file uploads from the user.
 * The uploaded file will be sent to the backend, processed chunk-by-chunk, and the results
 * returned to the frontend to be added to the conversation.
 */
async function uploadFile() {
    const fileInput = document.getElementById('file-input');
    const file = fileInput.files[0];  // Extract file from input

    // Ensure a file is selected
    if (!file) {
        showAlert('Please select a file before uploading.', 'error');
        return;
    }

    // Validate file type (allow 'txt', 'md', 'json')
    const allowedExtensions = ['txt', 'json', 'md'];
    const fileExtension = file.name.split('.').pop().toLowerCase();

    if (!allowedExtensions.includes(fileExtension)) {
        showAlert("Invalid file type. Allowed types: txt, md, json.", "error");
        return;
    }

    // Validate file size (<5MB)
    const fileSizeInMB = (file.size / (1024 * 1024)).toFixed(2);  // Convert to MB
    if (fileSizeInMB > 5) {
        showAlert('File too large. Maximum allowed size is 5MB.', 'error');
        return;
    }

    // Prepare and send the request for file upload (if passed validation)
    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/upload_file', {
            method: 'POST',
            body: formData,
        });

        const data = await response.json();
        if (!response.ok) {
            showAlert('Error: ' + data.message, 'error');
        } else {
            showAlert(data.message, 'success');
            appendMessage('assistant', data.analysis);  // Display the returned analysis
        }
    } catch (error) {
        console.error("File upload failed:", error);
        showAlert('Error uploading file. Please try again.', 'error');
    }
}

/**
 * Generic helper function to display alerts to the user.
 *
 * @param {string} message - The alert message.
 * @param {string} type - The type of alert ('success', 'error', etc.) for styling.
 */
function showAlert(message, type = 'info', duration = 3000) {
    const alertBox = document.createElement('div');
    alertBox.classList.add('alert', `alert-${type}`);
    alertBox.textContent = message;

    document.body.appendChild(alertBox);

    // Different timeout based on alert type
    if (type === 'error') {
        duration = 5000;
    }

    setTimeout(() => alertBox.remove(), duration);
}

// Use showAlert() across all functions that need it

/**
 * Auto-scroll the chat-history container to always show the most recent message.
 * This ensures that as new tokens or messages are appended, they are immediately visible to the user.
 */
function autoScroll() {
    const chatHistory = document.getElementById('chat-history');
    chatHistory.scrollTop = chatHistory.scrollHeight;
}