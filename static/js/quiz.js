// Generate quiz.js from the NeuroLearn AI spec. 
// Write complete, production-ready code. 
// Every function fully implemented. 

class NeuroLearnQuizManager {
    constructor() {
        this.chapterId = window.chapterId;
        this.questions = [];
        this.currIdx = 0;
        this.score = 0;
        this.xp = 0;
        this.timer = 30;
        this.timerRemaining = 30;
        this.timerInterval = null;
        this.hintUsed = false;
        
        this.cards = document.getElementById('quiz-card');
        this.optionsContainer = document.getElementById('options-container');
        this.btnNext = document.getElementById('btn-next');
        
        this.init();
    }

    async init() {
        try {
            console.log("📝 [QUIZ-INIT] Initializing quiz for chapter:", this.chapterId);
            const resp = await fetch(`/api/quiz-data/${this.chapterId}`);
            const data = await resp.json();
            
            if (!data.questions || !Array.isArray(data.questions)) {
                console.error("✗ [QUIZ-INIT] No questions in response:", data);
                this.showError("Quiz questions not found");
                return;
            }
            
            console.log(`📝 [QUIZ-INIT] Loaded ${data.questions.length} questions`);
            
            // Validate and sanitize questions
            this.questions = data.questions.map((q, idx) => {
                // Ensure correct field exists and is a valid index (0-3 for 4 options)
                let correctIndex = q.correct;
                if (typeof correctIndex !== 'number' || correctIndex < 0 || correctIndex >= (q.options ? q.options.length : 4)) {
                    console.warn(`⚠️ [QUIZ-INIT] Question ${idx} has invalid correct index: ${correctIndex}, defaulting to 0`);
                    correctIndex = 0;
                }
                
                const normalized = {
                    question: q.question || `Question ${idx + 1}`,
                    options: q.options || ["Option A", "Option B", "Option C", "Option D"],
                    correct: correctIndex,  // Ensure this is set correctly
                    explanation: q.explanation || "Great effort!",
                    difficulty: (q.difficulty || "medium").toLowerCase(),
                    concept_tag: q.concept_tag || "Concept"
                };
                
                console.log(`   ✓ Question ${idx + 1}: "${normalized.question.substring(0, 50)}..." [Correct: ${normalized.correct}]`);
                return normalized;
            });
            
            console.log("✓ [QUIZ-INIT] Questions validated and ready");
            this.setupEvents();
            this.renderQuestion();
        } catch (e) {
            console.error("✗ [QUIZ-INIT] Data Load Error:", e);
            this.showError(`Failed to load quiz: ${e.message}`);
        }
    }

    showError(message) {
        console.error("❌ [QUIZ] Error:", message);
        const card = document.getElementById('quiz-card');
        if (card) {
            card.innerHTML = `
                <div class="text-center py-12">
                    <p class="text-rose text-lg font-bold mb-4">❌ Quiz Error</p>
                    <p class="text-secondary mb-6">${message}</p>
                    <a href="/chapters" class="btn-primary">Return to Chapters</a>
                </div>
            `;
        }
    }

    setupEvents() {
        this.btnNext.onclick = () => this.nextQuestion();
        
        document.getElementById('toggle-ref').onclick = () => {
            const panel = document.getElementById('ref-panel');
            panel.classList.toggle('hidden');
            if (!this.hintUsed) {
                this.hintUsed = true;
                this.xp -= 20; // Penalty
                this.updateXP();
            }
        };

        // Voice Input
        const btnVoice = document.getElementById('btn-voice');
        if ('webkitSpeechRecognition' in window) {
            const recognition = new webkitSpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.lang = 'en-US';

            btnVoice.onclick = () => {
                recognition.start();
                btnVoice.classList.add('bg-cyan/20', 'animate-pulse');
            };

            recognition.onresult = (e) => {
                const text = e.results[0][0].transcript.toLowerCase();
                btnVoice.classList.remove('bg-cyan/20', 'animate-pulse');
                this.handleVoiceCommand(text);
            };
        } else {
            btnVoice.style.display = 'none';
        }
    }

    handleVoiceCommand(text) {
        const btns = this.optionsContainer.querySelectorAll('button');
        if (!btns || btns.length === 0) return;
        
        let targetIndex = -1;
        
        // Robust regex to extract spoken options like "option a", "a", "one", "first option"
        if (text.match(/\b(a|one|1|first)\b/i)) targetIndex = 0;
        else if (text.match(/\b(b|two|2|second|to|too)\b/i)) targetIndex = 1;
        else if (text.match(/\b(c|three|3|third|see)\b/i)) targetIndex = 2;
        else if (text.match(/\b(d|four|4|fourth|for)\b/i)) targetIndex = 3;

        // Fallback: check if user read out the actual text
        if (targetIndex === -1) {
            btns.forEach((btn, idx) => {
                // Remove the "A " or "B " prefix from innerText
                const btnText = btn.innerText.substring(2).trim().toLowerCase();
                if (btnText.length > 3 && (text.includes(btnText) || btnText.includes(text))) {
                    targetIndex = idx;
                }
            });
        }

        if (targetIndex >= 0 && targetIndex < btns.length) {
            console.log(`🎤 [VOICE] Parsed "${text}" -> Selected Option ${String.fromCharCode(65 + targetIndex)}`);
            btns[targetIndex].click();
        } else {
            console.log(`🎤 [VOICE] Failed to parse: "${text}"`);
            alert(`Didn't catch that: "${text}". Try saying "Option A", "B", "C", or "D".`);
        }
    }

    renderQuestion() {
        if (!this.questions || this.questions.length === 0) {
            console.error("❌ [RENDER-Q] No questions available");
            this.showError("No quiz questions available");
            return;
        }
        
        if (this.currIdx >= this.questions.length) {
            this.finishQuiz();
            return;
        }

        const q = this.questions[this.currIdx];
        
        // Validate question data
        if (!q.question || !q.options || !Array.isArray(q.options)) {
            console.error("❌ [RENDER-Q] Invalid question format:", q);
            this.showError("Invalid question format");
            return;
        }
        
        console.log(`📝 [RENDER-Q] Rendering question ${this.currIdx + 1}:`, q.question);
        
        document.getElementById('current-q').innerText = this.currIdx + 1;
        document.getElementById('total-q').innerText = this.questions.length;
        document.getElementById('quiz-progress').style.width = `${((this.currIdx + 1) / this.questions.length) * 100}%`;
        
        document.getElementById('concept-tag').innerText = q.concept_tag || "Chapter Core";
        document.getElementById('question-text').innerText = q.question;
        
        const badge = document.getElementById('difficulty-badge');
        const difficulty = (q.difficulty || "medium").toLowerCase();
        badge.innerText = difficulty.toUpperCase();
        badge.className = `text-[9px] font-bold uppercase py-1 px-3 rounded-full border ${difficulty === 'easy' ? 'text-emerald border-emerald' : (difficulty === 'medium' ? 'text-amber border-amber' : 'text-rose border-rose')}`;

        this.optionsContainer.innerHTML = '';
        q.options.forEach((opt, i) => {
            const btn = document.createElement('button');
            btn.className = 'glass p-5 text-left border-white/5 hover:border-violet/40 hover:bg-white/5 transition-all relative flex items-center gap-4 group';
            btn.innerHTML = `<span class="w-8 h-8 rounded-full border border-white/10 flex items-center justify-center text-xs group-hover:bg-violet group-hover:text-white transition-colors">${String.fromCharCode(65+i)}</span> <span class="text-sm font-medium">${opt}</span>`;
            btn.onclick = () => this.selectOption(i);
            this.optionsContainer.appendChild(btn);
        });

        document.getElementById('explanation-panel').classList.add('hidden');
        this.btnNext.disabled = true;
        
        this.startTimer(difficulty);
    }

    startTimer(diff) {
        if (this.timerInterval) clearInterval(this.timerInterval);
        
        diff = (diff || "medium").toLowerCase();
        this.timer = diff === 'easy' ? 30 : (diff === 'medium' ? 20 : 15);
        this.timerRemaining = this.timer;
        this.updateTimerUI();

        this.timerInterval = setInterval(() => {
            this.timerRemaining--;
            if (this.timerRemaining <= 0) {
                this.timerRemaining = 0;
                clearInterval(this.timerInterval);
                this.selectOption(-1); // Timeout
            }
            this.updateTimerUI();
        }, 1000);
    }

    updateTimerUI() {
        const offset = 125.6 * (1 - (this.timerRemaining / this.timer));
        document.getElementById('timer-stroke').style.strokeDashoffset = offset;
        document.getElementById('timer-text').innerText = `${this.timerRemaining}s`;
    }

    selectOption(idx) {
        clearInterval(this.timerInterval);
        const q = this.questions[this.currIdx];
        const buttons = this.optionsContainer.querySelectorAll('button');
        const correctIndex = q.correct; // Use 'correct' field, not 'correct_index'
        
        console.log(`📝 [QUIZ-SELECT] Question ${this.currIdx + 1}: Selected ${idx}, Correct is ${correctIndex}`);
        
        buttons.forEach((btn, i) => {
            btn.disabled = true;
            if (i === correctIndex) {
                btn.classList.add('bg-emerald/10', 'border-emerald');
                btn.innerHTML += `<i class="fas fa-check-circle text-emerald absolute right-6"></i>`;
            } else if (i === idx && idx !== correctIndex) {
                btn.classList.add('bg-rose/10', 'border-rose');
                btn.innerHTML += `<i class="fas fa-times-circle text-rose absolute right-6"></i>`;
            }
        });

        if (idx === correctIndex) {
            const points = q.difficulty === 'easy' ? 100 : (q.difficulty === 'medium' ? 150 : 250);
            this.xp += points;
            this.score++;
            console.log(`✓ [QUIZ-SELECT] Correct! +${points} XP (Total: ${this.xp})`);
        } else if (idx !== -1) {
            console.log(`✗ [QUIZ-SELECT] Wrong answer selected`);
        } else {
            console.log(`⏰ [QUIZ-SELECT] Timeout - no answer selected`);
        }

        document.getElementById('explanation-text').innerText = `💡 ${q.explanation}`;
        document.getElementById('explanation-panel').classList.remove('hidden');
        this.btnNext.disabled = false;
        this.updateXP();
    }

    updateXP() {
        document.getElementById('running-xp').innerText = Math.max(0, this.xp);
    }

    nextQuestion() {
        this.currIdx++;
        this.renderQuestion();
    }

    async finishQuiz() {
        const points = Math.max(0, this.xp);
        const ratio = this.questions.length > 0 ? Math.round((this.score / this.questions.length) * 100) : 0;
        
        console.log(`✓ [QUIZ-FINISH] Quiz completed!`);
        console.log(`   - Questions answered: ${this.score}/${this.questions.length}`);
        console.log(`   - Score percentage: ${ratio}%`);
        console.log(`   - XP earned: ${points}`);
        
        const resp = await fetch('/api/submit-quiz', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chapter_id: this.chapterId,
                score: ratio,
                xp_earned: points
            })
        });
        
        if (!resp.ok) {
            console.error("✗ [QUIZ-SUBMIT] Failed to submit quiz:", await resp.text());
            alert("Failed to submit quiz. Please try again.");
            return;
        }
        
        const result = await resp.json();
        console.log("✓ [QUIZ-SUBMIT] Response received:", result);
        
        if (result.redirect) {
            console.log(`🔄 [QUIZ-SUBMIT] Redirecting to: ${result.redirect}`);
            window.location.href = result.redirect;
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.quizManager = new NeuroLearnQuizManager();
});
