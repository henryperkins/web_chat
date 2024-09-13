// script.js

document.addEventListener('DOMContentLoaded', () => {
    // Initialize Socket.IO connection
    const socket = io({
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

    // Global Variables
    let MAX_TOKENS = 128000; // Default value
    let currentConversationId = sessionStorage.getItem('conversation_id') || null;

    // DOM Elements
    const chatHistory = document.getElementById('chat-history');
    const messageForm = document.getElementById('message-form');
    const userMessageInput = document.getElementById('user-message');
    const tokenProgressBar = document.getElementById('token-progress-bar');
    const tokenUsageText = document.getElementById('token-usage-text');
    const fewShotForm = document.getElementById('few-shot-form');
    const fileUploadForm = document.getElementById('file-upload-form');
    const conversationList = document.getElementById('conversation-list');
    const searchForm = document.getElementById('search-form');
    const searchInput = document.getElementById('search-input');

    // Check if essential elements exist
    if (!chatHistory || !messageForm || !userMessageInput || !tokenProgressBar || !tokenUsageText) {
        console.error('Essential DOM elements are missing.');
        return;
    }

    // Event Listeners
    messageForm.addEventListener('submit', function(event) {
        event.preventDefault();
        sendMessage();
    });

    if (fewShotForm) {
        fewShotForm.addEventListener('submit', function(event) {
            event.preventDefault();
            addFewShotExample();
        });
    } else {
        console.error('Element few-shot-form not found.');
    }

    if (fileUploadForm) {
        fileUploadForm.addEventListener('submit', function(event) {
            event.preventDefault();
            uploadFile();
        });
    } else {
        console.error('Element file-upload-form not found.');
    }

    if (searchForm) {
        searchForm.addEventListener('submit', function(event) {
            event.preventDefault();
            const query = searchInput.value.trim();
            if (query) {
                searchConversations(query);
            }
        });
    } else {
        console.error('Element search-form not found.');
    }

    // Buttons Event Listeners
    const newConversationButton = document.getElementById('new-conversation-button');
    const resetButton = document.getElementById('reset-button');
    const saveButton = document.getElementById('save-button');
    const listButton = document.getElementById('list-button');

    if (newConversationButton) {
        newConversationButton.addEventListener('click', startNewConversation);
    } else {
        console.error('Element new-conversation-button not found.');
    }

    if (resetButton) {
        resetButton.addEventListener('click', resetConversation);
    } else {
        console.error('Element reset-button not found.');
    }

    if (saveButton) {
        saveButton.addEventListener('click', saveConversation);
    } else {
        console.error('Element save-button not found.');
    }

    if (listButton) {
        listButton.addEventListener('click', listConversations);
    } else {
        console.error('Element list-button not found.');
    }

    // Socket event listeners
    socket.on('response_chunk', handleResponseChunk);
    socket.on('error', handleError);
    socket.on('token_usage', updateTokenUsage);

    // Global Error Handler
    window.addEventListener('unhandledrejection', function(event) {
        console.error('Unhandled promise rejection:', event.reason);
        notyf.error('An unexpected error occurred.');
    });

    // Functions

    function setCurrentConversation(conversationId) {
        currentConversationId = conversationId;
        sessionStorage.setItem('conversation_id', conversationId);
    }

    async function startNewConversation() {
        try {
            const data = await fetchJSON('/start_conversation', { method: 'POST' });
            setCurrentConversation(data.conversation_id);
            chatHistory.innerHTML = '';
            notyf.success('Started a new conversation.');
            updateTokenUsage({ total_tokens_used: 0 });
            listConversations();
        } catch (error) {
            notyf.error(error.message);
        }
    }

    function sendMessage() {
        const message = userMessageInput.value.trim();
        if (!message) return;

        appendMessage('user', message);

        socket.emit('send_message', { message: message }, (error) => {
            if (error) {
                notyf.error('Failed to send message.');
            }
        });

        userMessageInput.value = '';
    }

    function appendMessage(role, content) {
        if (!chatHistory) {
            console.error('chatHistory element not found.');
            return;
        }
        const messageElement = document.createElement('div');
        messageElement.classList.add(`${role}-message`);
        messageElement.textContent = content;
        chatHistory.appendChild(messageElement);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function handleResponseChunk(data) {
        if (data && data.chunk) {
            appendMessage('assistant', data.chunk);
        } else {
            console.error('Invalid data received in handleResponseChunk.');
        }
    }

    function handleError(data) {
        console.error('Error:', data.message);
        notyf.error('An error occurred. Please try again.');
    }

    function updateTokenUsage(data) {
        const tokensUsed = data.total_tokens_used || 0;
        tokenProgressBar.value = tokensUsed;
        tokenUsageText.textContent = `Token Usage: ${tokensUsed} / ${MAX_TOKENS}`;
    }

    async function resetConversation() {
        if (!currentConversationId) {
            notyf.error('No active conversation to reset.');
            return;
        }
        try {
            const data = await fetchJSON('/reset_conversation', { method: 'POST' });
            chatHistory.innerHTML = '';
            notyf.success(data.message);
            updateTokenUsage({ total_tokens_used: 0 });
        } catch (error) {
            notyf.error(error.message);
        }
    }

    async function saveConversation() {
        // Since conversations are automatically saved in the database, this function could notify the user
        notyf.success('Conversation is automatically saved.');
    }

    async function listConversations() {
        try {
            const data = await fetchJSON('/list_conversations');
            renderConversations(data.conversations);
        } catch (error) {
            notyf.error(error.message);
        }
    }

    function renderConversations(conversations) {
        conversationList.innerHTML = '';
        if (conversations.length === 0) {
            const listItem = document.createElement('li');
            listItem.textContent = 'No conversations found.';
            conversationList.appendChild(listItem);
        } else {
            conversations.forEach(conv => {
                const listItem = document.createElement('li');

                const span = document.createElement('span');
                const createdAt = new Date(conv.created_at).toLocaleString();
                span.textContent = `Conversation ${createdAt}`;
                listItem.appendChild(span);

                const loadButton = document.createElement('button');
                loadButton.textContent = 'Load';
                loadButton.classList.add('btn', 'btn-sm', 'btn-primary');
                loadButton.addEventListener('click', () => loadConversation(conv.conversation_id));
                listItem.appendChild(loadButton);

                conversationList.appendChild(listItem);
            });
        }
    }

    async function loadConversation(conversationId) {
        try {
            const data = await fetchJSON(`/load_conversation/${encodeURIComponent(conversationId)}`);
            setCurrentConversation(conversationId);
            chatHistory.innerHTML = '';
            if (data.conversation && data.conversation.length > 0) {
                data.conversation.forEach(entry => {
                    appendMessage(entry.role, entry.content);
                });
            }
            notyf.success('Conversation loaded.');
            // If the server provides total_tokens_used, update it; otherwise, you may need to recalculate or omit this
            // updateTokenUsage({ total_tokens_used: data.total_tokens_used || 0 });
        } catch (error) {
            notyf.error(error.message);
        }
    }

    async function searchConversations(query) {
        try {
            const data = await fetchJSON(`/search_conversations?q=${encodeURIComponent(query)}`);
            renderSearchResults(data.conversations);
        } catch (error) {
            notyf.error(error.message);
        }
    }
    

    function renderSearchResults(conversations) {
        conversationList.innerHTML = '';
        if (conversations.length === 0) {
            const listItem = document.createElement('li');
            listItem.textContent = 'No conversations found.';
            conversationList.appendChild(listItem);
        } else {
            conversations.forEach(conv => {
                const listItem = document.createElement('li');

                const span = document.createElement('span');
                const createdAt = new Date(conv.created_at).toLocaleString();
                span.textContent = `Conversation ${createdAt}`;
                listItem.appendChild(span);

                const loadButton = document.createElement('button');
                loadButton.textContent = 'Load';
                loadButton.classList.add('btn', 'btn-sm', 'btn-primary');
                loadButton.addEventListener('click', () => loadConversation(conv.conversation_id));
                listItem.appendChild(loadButton);

                conversationList.appendChild(listItem);
            });
        }
    }

    async function addFewShotExample() {
        const userPrompt = document.getElementById('user-prompt').value.trim();
        const assistantResponse = document.getElementById('assistant-response').value.trim();

        if (!userPrompt || !assistantResponse) {
            notyf.error('Both user prompt and assistant response are required.');
            return;
        }

        try {
            const data = await fetchJSON('/add_few_shot_example', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_prompt: userPrompt, assistant_response: assistantResponse })
            });
            notyf.success(data.message);
            document.getElementById('user-prompt').value = '';
            document.getElementById('assistant-response').value = '';
        } catch (error) {
            notyf.error(error.message);
        }
    }

    async function uploadFile() {
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

        const fileSizeInMB = file.size / (1024 * 1024);
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
                throw new Error(data.message || 'Error uploading file.');
            }
            notyf.success(data.message);
            appendMessage('assistant', data.analysis);
        } catch (error) {
            notyf.error(error.message || 'Error uploading file. Please try again.');
        }
    }

    // Utility function for fetch requests with error handling
    async function fetchJSON(url, options = {}) {
        try {
            const response = await fetch(url, options);
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || 'An error occurred.');
            }
            return data;
        } catch (error) {
            console.error('Fetch error:', error);
            throw error;
        }
    }

    // Fetch configuration from the server
    async function getConfig() {
        try {
            const data = await fetchJSON('/get_config');
            MAX_TOKENS = data.max_tokens || MAX_TOKENS;
            tokenProgressBar.max = MAX_TOKENS;
            tokenUsageText.textContent = `Token Usage: 0 / ${MAX_TOKENS}`;
        } catch (error) {
            console.error('Failed to fetch configuration:', error);
        }
    }

    // Initialize the app
    getConfig();
    listConversations();

    // If there's a current conversation ID, load it
    if (currentConversationId) {
        loadConversation(currentConversationId);
    }
});
