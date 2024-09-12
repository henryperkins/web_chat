// Initialize Socket.IO connection
const socket = io('http://localhost:5000', {
    transports: ['websocket'],
    reconnection: true,
    reconnectionDelay: 1000,
    maxReconnectionAttempts: 5
});

// Initialize Notyf for notifications
const notyf = new Notyf({
    duration: 3000,
    position: { x: 'right', y: 'top' },
    types: [
        {
            type: 'success',
            background: '#28a745',
            icon: false
        },
        {
            type: 'error',
            background: '#dc3545',
            icon: false
        }
    ]
});

// DOM Elements
const chatHistory = document.getElementById('chat-history');
const messageForm = document.getElementById('message-form');
const userMessageInput = document.getElementById('user-message');
const tokenProgressBar = document.getElementById('token-progress-bar');
const tokenUsageText = document.getElementById('token-usage-text');
const fewShotForm = document.getElementById('few-shot-form');
const fileUploadForm = document.getElementById('file-upload-form');
const conversationList = document.getElementById('conversation-list');

// Event Listeners
messageForm.addEventListener('submit', sendMessage);
fewShotForm.addEventListener('submit', addFewShotExample);
fileUploadForm.addEventListener('submit', uploadFile);

// Socket event listeners
socket.on('response_chunk', handleResponseChunk);
socket.on('error', handleError);
socket.on('token_usage', updateTokenUsage);

// Functions
function sendMessage(event) {
    event.preventDefault();
    const message = userMessageInput.value.trim();
    if (!message) return;

    appendMessage('user', message);
    socket.emit('send_message', { message: message });
    userMessageInput.value = '';
}

function appendMessage(role, content) {
    const messageElement = document.createElement('div');
    messageElement.classList.add(`${role}-message`);
    messageElement.textContent = content;
    chatHistory.appendChild(messageElement);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function handleResponseChunk(data) {
    appendMessage('assistant', data.chunk);
}

function handleError(data) {
    console.error(data.message);
    notyf.error(data.message);
}

function updateTokenUsage(data) {
    tokenProgressBar.value = data.total_tokens_used;
    tokenUsageText.textContent = `Token Usage: ${data.total_tokens_used} / 128000`;
}

async function resetConversation() {
    try {
        const response = await fetch('/reset_conversation', { method: 'POST' });
        const data = await response.json();
        chatHistory.innerHTML = '';
        notyf.success(data.message);
    } catch (error) {
        notyf.error('Failed to reset conversation. Please try again.');
    }
}

async function saveConversation() {
    try {
        const response = await fetch('/save_history', { method: 'POST' });
        const data = await response.json();
        notyf.success(data.message);
        listConversations();
    } catch (error) {
        notyf.error('Failed to save conversation. Please try again.');
    }
}

async function listConversations() {
    try {
        const response = await fetch('/list_conversations');
        const data = await response.json();
        renderConversations(data.conversations);
    } catch (error) {
        notyf.error('Failed to fetch conversations. Please try again.');
    }
}

function renderConversations(conversations) {
    conversationList.innerHTML = '';
    if (conversations.length === 0) {
        conversationList.innerHTML = '<li>No conversations saved.</li>';
    } else {
        conversations.forEach(filename => {
            const listItem = document.createElement('li');
            listItem.innerHTML = `
                <span>${filename}</span>
                <div>
                    <button onclick="loadConversation('${filename}')" class="btn btn-sm btn-primary">Load</button>
                    <a href="/download_conversation/${filename}" download class="btn btn-sm btn-secondary">Download</a>
                </div>
            `;
            conversationList.appendChild(listItem);
        });
    }
}

async function loadConversation(filename) {
    try {
        const response = await fetch(`/load_conversation/${filename}`);
        const data = await response.json();
        chatHistory.innerHTML = '';
        data.conversation.forEach(entry => {
            appendMessage(entry.role, entry.content);
        });
        notyf.success(`Loaded conversation: ${filename}`);
    } catch (error) {
        notyf.error('Failed to load conversation. Please try again.');
    }
}

async function addFewShotExample(event) {
    event.preventDefault();
    const userPrompt = document.getElementById('user-prompt').value;
    const assistantResponse = document.getElementById('assistant-response').value;

    if (!userPrompt || !assistantResponse) {
        notyf.error('Both user prompt and assistant response are required.');
        return;
    }

    try {
        const response = await fetch('/add_few_shot_example', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_prompt: userPrompt, assistant_response: assistantResponse })
        });
        const data = await response.json();
        notyf.success(data.message);
        document.getElementById('user-prompt').value = '';
        document.getElementById('assistant-response').value = '';
    } catch (error) {
        notyf.error('Failed to add few-shot example. Please try again.');
    }
}

async function uploadFile(event) {
    event.preventDefault();
    const fileInput = document.getElementById('file-input');
    const file = fileInput.files[0];

    if (!file) {
        notyf.error('Please select a file before uploading.');
        return;
    }

    const allowedExtensions = ['txt', 'json', 'md'];
    const fileExtension = file.name.split('.').pop().toLowerCase();

    if (!allowedExtensions.includes(fileExtension)) {
        notyf.error('Invalid file type. Allowed types: txt, md, json.');
        return;
    }

    const fileSizeInMB = (file.size / (1024 * 1024)).toFixed(2);
    if (fileSizeInMB > 5) {
        notyf.error('File too large. Maximum allowed size is 5MB.');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/upload_file', { method: 'POST', body: formData });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.message);
        }
        notyf.success(data.message);
        appendMessage('assistant', data.analysis);
    } catch (error) {
        notyf.error(error.message || 'Error uploading file. Please try again.');
    }
}

// Initialize the app
listConversations();