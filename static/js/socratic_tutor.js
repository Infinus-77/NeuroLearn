/**
 * NeuroLearn AI — Socratic Tutor Module
 * Floating chat widget that answers student questions using chapter context.
 * Uses webkitSpeechRecognition for voice input (same pattern as quiz.js).
 */

class SocraticTutor {
    constructor(options = {}) {
        this.chapterId = options.chapterId || null;
        this.topicId = options.topicId || null;
        this.maxMessages = 10;
        this.messageCount = 0;
        this.isOpen = false;
        this.isLoading = false;
        this.recognition = null;
        this.isListening = false;

        this.init();
    }

    init() {
        this._buildUI();
        this._setupEvents();
        this._setupVoiceInput();
        console.log('💬 [TUTOR] Socratic Tutor initialized');
    }

    _buildUI() {
        // Floating Action Button
        const fab = document.createElement('button');
        fab.id = 'socratic-fab';
        fab.className = 'socratic-fab';
        fab.innerHTML = '<i class="fas fa-question"></i>';
        fab.title = 'Ask your AI Tutor';
        document.body.appendChild(fab);

        // Chat Panel
        const panel = document.createElement('div');
        panel.id = 'socratic-panel';
        panel.className = 'socratic-panel socratic-panel-hidden';
        panel.innerHTML = `
            <div class="socratic-header">
                <div class="socratic-header-info">
                    <span class="socratic-avatar">🏛️</span>
                    <div>
                        <h4 class="socratic-title">Socrates</h4>
                        <span class="socratic-subtitle">Your AI Tutor</span>
                    </div>
                </div>
                <button id="socratic-close" class="socratic-close-btn">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <div id="socratic-messages" class="socratic-messages">
                <div class="socratic-bubble socratic-bubble-tutor">
                    <p>Hello! 👋 I'm Socrates, your learning guide. Ask me anything about this chapter and I'll help you understand it better!</p>
                </div>
            </div>
            <div id="socratic-limit-banner" class="socratic-limit-banner hidden">
                <span>🎓</span>
                <p>Great session! You've asked great questions. Move on to the game to test your knowledge!</p>
            </div>
            <div id="socratic-input-area" class="socratic-input-area">
                <input type="text" id="socratic-input" class="socratic-input" placeholder="Ask a question..." autocomplete="off">
                <button id="socratic-mic" class="socratic-mic-btn" title="Voice input">
                    <i class="fas fa-microphone"></i>
                </button>
                <button id="socratic-send" class="socratic-send-btn" title="Send">
                    <i class="fas fa-paper-plane"></i>
                </button>
            </div>
        `;
        document.body.appendChild(panel);

        // Store refs
        this.fab = fab;
        this.panel = panel;
        this.messagesContainer = document.getElementById('socratic-messages');
        this.inputField = document.getElementById('socratic-input');
        this.sendBtn = document.getElementById('socratic-send');
        this.micBtn = document.getElementById('socratic-mic');
        this.closeBtn = document.getElementById('socratic-close');
        this.limitBanner = document.getElementById('socratic-limit-banner');
        this.inputArea = document.getElementById('socratic-input-area');
    }

    _setupEvents() {
        this.fab.addEventListener('click', () => this.togglePanel());
        this.closeBtn.addEventListener('click', () => this.togglePanel());

        this.sendBtn.addEventListener('click', () => {
            const text = this.inputField.value.trim();
            if (text) this.sendMessage(text);
        });

        this.inputField.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                const text = this.inputField.value.trim();
                if (text) this.sendMessage(text);
            }
        });
    }

    _setupVoiceInput() {
        if (!('webkitSpeechRecognition' in window)) {
            this.micBtn.style.display = 'none';
            return;
        }

        this.recognition = new webkitSpeechRecognition();
        this.recognition.continuous = false;
        this.recognition.interimResults = false;
        this.recognition.lang = 'en-US';

        this.micBtn.addEventListener('click', () => {
            if (this.isListening) {
                this.recognition.stop();
                return;
            }
            this.recognition.start();
            this.isListening = true;
            this.micBtn.classList.add('socratic-mic-active');
        });

        this.recognition.onresult = (e) => {
            const transcript = e.results[0][0].transcript;
            this.isListening = false;
            this.micBtn.classList.remove('socratic-mic-active');
            this.inputField.value = transcript;
            this.sendMessage(transcript);
        };

        this.recognition.onerror = () => {
            this.isListening = false;
            this.micBtn.classList.remove('socratic-mic-active');
        };

        this.recognition.onend = () => {
            this.isListening = false;
            this.micBtn.classList.remove('socratic-mic-active');
        };
    }

    togglePanel() {
        this.isOpen = !this.isOpen;
        if (this.isOpen) {
            this.panel.classList.remove('socratic-panel-hidden');
            this.fab.classList.add('socratic-fab-active');
            this.fab.innerHTML = '<i class="fas fa-times"></i>';
            setTimeout(() => this.inputField.focus(), 300);
        } else {
            this.panel.classList.add('socratic-panel-hidden');
            this.fab.classList.remove('socratic-fab-active');
            this.fab.innerHTML = '<i class="fas fa-question"></i>';
        }
    }

    async sendMessage(text) {
        if (this.isLoading || this.messageCount >= this.maxMessages) return;

        // Render student bubble
        this.renderBubble(text, 'student');
        this.inputField.value = '';
        this.messageCount++;

        // Show loading
        this.isLoading = true;
        const loadingId = this._showLoading();

        try {
            const response = await fetch('/api/ask-tutor', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    question: text,
                    chapter_id: this.chapterId,
                    topic_id: this.topicId
                })
            });

            this._removeLoading(loadingId);

            // Check if response is OK before parsing JSON
            if (!response.ok) {
                console.warn(`💬 [TUTOR] API returned status ${response.status}`);
                this.renderBubble('Service temporarily unavailable. Please try again.', 'tutor');
                return;
            }

            const data = await response.json();

            if (data.success && data.answer) {
                this.renderBubble(data.answer, 'tutor');
            } else {
                this.renderBubble(data.error || 'Sorry, I couldn\'t process that. Try rephrasing!', 'tutor');
            }
        } catch (error) {
            this._removeLoading(loadingId);
            
            // Graceful error handling for network/parsing issues
            if (error instanceof SyntaxError) {
                console.error('💬 [TUTOR] Response parse error:', error.message);
                this.renderBubble('Oops! Invalid response format. Please try again.', 'tutor');
            } else if (error instanceof TypeError) {
                console.error('💬 [TUTOR] Network error:', error.message);
                this.renderBubble('Connection lost. Please check your internet and try again.', 'tutor');
            } else {
                console.error('💬 [TUTOR] Error:', error);
                this.renderBubble('Oops! Something went wrong. Please try again.', 'tutor');
            }
        }

        this.isLoading = false;
        this.messageCount++;

        // Check message limit
        if (this.messageCount >= this.maxMessages) {
            this.inputArea.classList.add('hidden');
            this.limitBanner.classList.remove('hidden');
        }
    }

    renderBubble(text, role) {
        const bubble = document.createElement('div');
        bubble.className = `socratic-bubble socratic-bubble-${role}`;
        bubble.innerHTML = `<p>${this._escapeHtml(text)}</p>`;
        this.messagesContainer.appendChild(bubble);
        this._scrollToBottom();
    }

    _showLoading() {
        const id = 'loading-' + Date.now();
        const el = document.createElement('div');
        el.id = id;
        el.className = 'socratic-bubble socratic-bubble-tutor socratic-loading';
        el.innerHTML = `
            <div class="socratic-typing">
                <span></span><span></span><span></span>
            </div>
        `;
        this.messagesContainer.appendChild(el);
        this._scrollToBottom();
        return id;
    }

    _removeLoading(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    _scrollToBottom() {
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}

window.SocraticTutor = SocraticTutor;
