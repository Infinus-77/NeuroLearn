// Generate game_engine.js from the NeuroLearn AI spec. 
// Write complete, production-ready code. 
// Every function fully implemented. 

class NeuroLearnGameEngine {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.width = 800;
        this.height = 500;
        
        // Internal State
        this.type = window.gameType;
        this.rawData = window.gameData;
        this.items = [];
        this.zones = [];
        this.lines = [];
        this.score = 100;
        this.completed = false;
        
        // Interaction State
        this.mouseX = 0;
        this.mouseY = 0;
        this.isDragging = false;
        this.dragElement = null;
        this.offsetX = 0;
        this.offsetY = 0;

        // Visuals (Design System)
        this.colors = {
            bg: '#0a0a0f',
            violet: '#7c3aed',
            cyan: '#06b6d4',
            amber: '#f59e0b',
            emerald: '#10b981',
            rose: '#f43f5e',
            cardBg: 'rgba(255, 255, 255, 0.04)',
            cardHover: 'rgba(255, 255, 255, 0.12)',
            text: '#f1f5f9'
        };

        this.init();
    }

    init() {
        console.log("🎮 [GAME-INIT] Initializing game engine...");
        console.log("   - Game Type:", this.type);
        console.log("   - Game Data:", this.rawData);
        
        // Validate that we have data
        if (!this.rawData || !Array.isArray(this.rawData) || this.rawData.length === 0) {
            console.warn("⚠️ [GAME-INIT] No game data available!");
            this.showErrorState("Game data is empty or missing");
            return;
        }
        
        this.canvas.width = this.width;
        this.canvas.height = this.height;
        this.setupGame();
        
        // Mouse Events - use the correct method names
        this.canvas.onmousedown = (e) => this.onDown(e);
        this.canvas.onmousemove = (e) => this.onMove(e);
        this.canvas.onmouseup = (e) => this.onUp(e);
        
        // Alternative event listener setup (backup)
        this.canvas.addEventListener('mousedown', this.onDown?.bind(this));
        this.canvas.addEventListener('mousemove', this.onMove?.bind(this));
        this.canvas.addEventListener('mouseup', this.onUp?.bind(this));
        
        // Touch Events
        this.canvas.addEventListener('touchstart', (e) => this.onDown?.(this.touchToMouse(e)), {passive: false});
        this.canvas.addEventListener('touchmove', (e) => this.onMove?.(this.touchToMouse(e)), {passive: false});
        this.canvas.addEventListener('touchend', (e) => this.onUp?.(e), {passive: false});

        // Hide loader
        const loader = document.getElementById('loader');
        if (loader) loader.classList.add('hidden');
        
        this.loop();
        console.log("✓ [GAME-INIT] Game initialized successfully");
    }

    showErrorState(message) {
        console.error("❌ [GAME] Error:", message);
        this.ctx.fillStyle = '#0d0d1a';
        this.ctx.fillRect(0, 0, this.width, this.height);
        
        this.ctx.fillStyle = '#f43f5e';
        this.ctx.font = 'bold 32px Inter';
        this.ctx.textAlign = 'center';
        this.ctx.fillText('❌ Game Error', this.width/2, this.height/2 - 40);
        
        this.ctx.fillStyle = '#cbd5e1';
        this.ctx.font = '18px Inter';
        this.ctx.fillText(message, this.width/2, this.height/2 + 20);
        
        this.ctx.fillStyle = '#94a3b8';
        this.ctx.font = '16px Inter';
        this.ctx.fillText('Try refreshing the page', this.width/2, this.height/2 + 60);
    }

    touchToMouse(e) {
        e.preventDefault();
        return {
            clientX: e.touches[0].clientX,
            clientY: e.touches[0].clientY,
            target: this.canvas
        };
    }

    getMousePos(e) {
        const rect = this.canvas.getBoundingClientRect();
        const scaleX = this.canvas.width / rect.width;
        const scaleY = this.canvas.height / rect.height;
        return {
            x: (e.clientX - rect.left) * scaleX,
            y: (e.clientY - rect.top) * scaleY
        };
    }

    setupGame() {
        if (this.type === 'sequence_sort') {
            const spacing = this.width / (this.rawData.length + 1);
            this.rawData.forEach((it, i) => {
                // Drop zone
                this.zones.push({
                    id: i + 1, x: spacing * (i + 1) - 60, y: 150, w: 120, h: 70,
                    correct_id: it.correct_position || it.id, occupiedBy: null
                });
                // Draggable item
                this.items.push({
                    id: it.id, type: 'card', text: it.text,
                    x: 50 + Math.random() * (this.width - 200),
                    y: 320 + Math.random() * 80,
                    w: 120, h: 70, isDragging: false, snapZone: null, correct: false
                });
            });
        } 
        else if (this.type === 'label_match') {
            this.rawData.forEach((it, i) => {
                const zx = 100 + (i % 3) * 230;
                const zy = 100 + Math.floor(i / 3) * 150;
                this.zones.push({
                    id: it.correct_zone || it.id, x: zx, y: zy, w: 160, h: 50,
                    label: it.label, occupiedBy: null
                });
                this.items.push({
                    id: it.correct_zone || it.id, type: 'label', text: it.label,
                    x: 100 + i * 150, y: 420, w: 140, h: 40,
                    isDragging: false, snapZone: null, correct: false,
                    accent: it.hint_color || this.colors.violet
                });
            });
        }
        else if (this.type === 'true_false_blitz') {
            this.state = { currIdx: 0, timer: 30, streak: 0 };
            this.items.push({ id: 'true', type: 'btn', text: '✓ TRUE', x: 100, y: 350, w: 280, h: 80, color: this.colors.cyan });
            this.items.push({ id: 'false', type: 'btn', text: '✗ FALSE', x: 420, y: 350, w: 280, h: 80, color: this.colors.rose });
            this.timerInterval = setInterval(() => {
                if (!this.completed && this.state.timer > 0) this.state.timer--;
            }, 1000);
        }
        else if (this.type === 'concept_connect') {
            this.state = { currDraw: null };
            const leftItems = this.rawData.map(it => ({ id: 'L_'+it.id, pairId: it.id, text: it.left, type: 'node_L' }));
            const rightItems = this.rawData.map(it => ({ id: 'R_'+it.id, pairId: it.id, text: it.right, type: 'node_R' }));
            const shuffledRight = [...rightItems].sort(() => Math.random() - 0.5);
            
            const vSpace = 400 / leftItems.length;
            leftItems.forEach((it, i) => {
                this.items.push({ ...it, x: 100, y: 80 + i * vSpace, r: 20, connectedTo: null });
            });
            shuffledRight.forEach((it, i) => {
                this.items.push({ ...it, x: 700, y: 80 + i * vSpace, r: 20, connectedTo: null });
            });
        }
        else if (this.type === 'word_builder') {
            const word = this.rawData[0].term;
            const scrambled = this.rawData[0].scrambled;
            const definition = this.rawData[0].definition;
            this.state = { word, definition, slots: [] };
            
            const wSpacing = 60;
            const startX = this.width/2 - (word.length * wSpacing)/2;
            for(let i=0; i<word.length; i++) {
                this.zones.push({ id: i, x: startX + i*wSpacing, y: 200, w: 50, h: 50, expected: word[i], occupiedBy: null });
                this.items.push({
                    id: 'letter_'+i, type: 'letter', text: scrambled[i],
                    x: 100 + Math.random() * (this.width - 200),
                    y: 350 + Math.random() * 80, w: 50, h: 50, 
                    isDragging: false, snapZone: null, correct: false
                });
            }
        }
        else if (this.type === 'code_drop') {
            const questionData = this.rawData[0] || {};
            const questionText = questionData.question || "Drag the proper code below.";
            this.state = { currentQuestion: questionText };
            
            // Answer Drop Zone
            this.zones.push({
                id: 'codezone', 
                x: this.width / 2 - 200, 
                y: 180, 
                w: 400, 
                h: 80,
                expected: questionData.expected_code, 
                occupiedBy: null, 
                label: "Drop Correct Code Here"
            });
            
            // Draggable Snippets
            const choices = questionData.choices || [];
            const wSpacing = this.width / (choices.length + 1);
            choices.forEach((choice, i) => {
                this.items.push({
                    id: 'snippet_' + i, 
                    type: 'card', 
                    text: choice,
                    snippetText: choice,
                    x: wSpacing * (i + 1) - 90, 
                    y: 350, 
                    w: 180, 
                    h: 60,
                    isDragging: false, snapZone: null, correct: false,
                    accent: this.colors.emerald
                });
            });
        }
    }

    onDown(e) {
        if(this.completed) return;
        const {x, y} = this.getMousePos(e);
        this.mouseX = x; this.mouseY = y;

        if (this.type === 'true_false_blitz') {
            if (this.state.feedbackMsg) return; // Ignore input while showing feedback
            this.items.forEach(btn => {
                if (x >= btn.x && x <= btn.x + btn.w && y >= btn.y && y <= btn.y + btn.h) {
                    this.evalBlitz(btn.id === 'true');
                }
            });
            return;
        }

        if (this.type === 'concept_connect') {
            const node = this.items.find(it => it.type === 'node_L' && !it.connectedTo && Math.hypot(it.x - x, it.y - y) < it.r);
            if (node) this.state.currDraw = { start: node, x, y };
            return;
        }

        for (let i = this.items.length - 1; i >= 0; i--) {
            const it = this.items[i];
            if (x >= it.x && x <= it.x + it.w && y >= it.y && y <= it.y + it.h) {
                this.isDragging = true;
                this.dragElement = it;
                it.isDragging = true;
                this.offsetX = x - it.x;
                this.offsetY = y - it.y;
                if (it.snapZone) {
                    it.snapZone.occupiedBy = null;
                    it.snapZone = null;
                }
                this.items.push(this.items.splice(i, 1)[0]);
                break;
            }
        }
    }

    onMove(e) {
        const {x, y} = this.getMousePos(e);
        this.mouseX = x; this.mouseY = y;
        if (this.isDragging && this.dragElement) {
            this.dragElement.x = x - this.offsetX;
            this.dragElement.y = y - this.offsetY;
        }
        if (this.state && this.state.currDraw) {
            this.state.currDraw.x = x;
            this.state.currDraw.y = y;
        }
    }

    onUp(e) {
        if (this.type === 'concept_connect' && this.state.currDraw) {
            const target = this.items.find(it => it.type === 'node_R' && !it.connectedTo && Math.hypot(it.x - this.mouseX, it.y - this.mouseY) < it.r);
            if (target && target.pairId === this.state.currDraw.start.pairId) {
                this.state.currDraw.start.connectedTo = target;
                target.connectedTo = this.state.currDraw.start;
                this.lines.push({ n1: this.state.currDraw.start, n2: target, color: this.colors.emerald });
                this.checkWin();
            }
            this.state.currDraw = null;
        }

        if (this.isDragging && this.dragElement) {
            const it = this.dragElement;
            it.isDragging = false;
            let bestZone = this.zones.find(z => !z.occupiedBy && Math.abs(z.x + z.w/2 - (it.x + it.w/2)) < (it.w/2 + z.w/2 - 20) && Math.abs(z.y + z.h/2 - (it.y + it.h/2)) < (it.h/2 + z.h/2 - 20));
            
            if (bestZone) {
                it.x = bestZone.x + (bestZone.w - it.w)/2;
                it.y = bestZone.y + (bestZone.h - it.h)/2;
                it.snapZone = bestZone;
                bestZone.occupiedBy = it;
                this.checkWin();
            }
            this.isDragging = false;
            this.dragElement = null;
        }
    }

    evalBlitz(choice) {
        const curr = this.rawData[this.state.currIdx];
        const isCorrect = choice === curr.answer;
        
        if (isCorrect) {
            this.state.streak++;
            this.state.feedbackMsg = 'CORRECT!';
            this.state.feedbackColor = this.colors.emerald;
            this.spawnConfetti(this.mouseX, this.mouseY);
        } else {
            this.state.streak = 0;
            this.state.feedbackMsg = 'INCORRECT';
            this.state.feedbackColor = this.colors.rose;
        }
        
        // Show feedback for 1.5s then move on
        setTimeout(() => {
            this.state.feedbackMsg = null;
            this.state.currIdx++;
            this.state.timer = 15;
            if (this.state.currIdx >= this.rawData.length) {
                this.triggerWin();
            }
        }, 1500);
    }

    checkWin() {
        let win = false;
        if (this.type === 'concept_connect') {
            win = this.items.filter(it => it.type === 'node_L').every(it => it.connectedTo);
        } else if (this.type === 'code_drop') {
            // For code_drop, check if the dropped item's snippetText matches expected
            win = this.zones.every(z => z.occupiedBy && z.occupiedBy.snippetText === z.expected);
        } else {
            win = this.zones.every(z => z.occupiedBy);
        }
        
        if (win) {
            document.getElementById('submit-board-container').classList.remove('hidden');
        }
    }

    triggerWin() {
        this.completed = true;
        const overlay = document.getElementById('game-overlay');
        overlay.classList.remove('opacity-0', 'pointer-events-none', 'scale-95');
        confetti({ particleCount: 150, spread: 70, origin: { y: 0.6 } });
    }

    loop() {
        requestAnimationFrame(() => this.loop());
        this.ctx.clearRect(0, 0, this.width, this.height);
        this.draw();
    }

    draw() {
        const ctx = this.ctx;
        
        // Draw Zones
        this.zones.forEach(z => {
            ctx.setLineDash([5, 5]);
            ctx.strokeStyle = this.colors.border_glass || 'rgba(255,255,255,0.1)';
            ctx.strokeRect(z.x, z.y, z.w, z.h);
            ctx.setLineDash([]);
            if (z.label) {
                ctx.fillStyle = this.colors.cyan;
                ctx.font = '12px Inter';
                ctx.textAlign = 'center';
                ctx.fillText(z.label, z.x + z.w/2, z.y - 10);
            }
        });

        // Draw Lines
        this.lines.forEach(l => {
            ctx.beginPath();
            ctx.moveTo(l.n1.x, l.n1.y); ctx.lineTo(l.n2.x, l.n2.y);
            ctx.strokeStyle = l.color; ctx.lineWidth = 3; ctx.stroke();
        });
        if (this.state && this.state.currDraw) {
            ctx.beginPath();
            ctx.moveTo(this.state.currDraw.start.x, this.state.currDraw.start.y);
            ctx.lineTo(this.state.currDraw.x, this.state.currDraw.y);
            ctx.strokeStyle = this.colors.violet; ctx.lineWidth = 2; ctx.setLineDash([5,5]); ctx.stroke(); ctx.setLineDash([]);
        }

        // Draw Blitz
        if (this.type === 'true_false_blitz' && !this.completed) {
            const curr = this.rawData && this.rawData[this.state.currIdx];
            if (!curr) {
                ctx.fillStyle = '#f43f5e';
                ctx.font = 'bold 24px Inter';
                ctx.textAlign = 'center';
                ctx.fillText('❌ No statements loaded', 400, 180);
                return;
            }
            
            if (this.state.feedbackMsg) {
                // Show feedback text overlay instead of question
                ctx.fillStyle = this.state.feedbackColor;
                ctx.font = 'bold 48px Space Grotesk';
                ctx.textAlign = 'center';
                ctx.shadowBlur = 20;
                ctx.shadowColor = this.state.feedbackColor;
                ctx.fillText(this.state.feedbackMsg, 400, 180);
                if (!this.state.feedbackMsg.includes("CORRECT!")) {
                    ctx.font = '16px Inter';
                    ctx.shadowBlur = 0;
                    ctx.fillStyle = '#cbd5e1';
                    this.wrapText(ctx, curr.explanation || "Review the material.", 400, 240, 500, 24);
                }
                ctx.shadowBlur = 0;
            } else {
                ctx.fillStyle = '#fff'; ctx.font = '24px Space Grotesk'; ctx.textAlign = 'center';
                this.wrapText(ctx, curr.statement || "Statement not available", 400, 180, 600, 30);
            }
            
            ctx.fillStyle = this.colors.amber; ctx.font = '16px Inter';
            ctx.fillText(`Time: ${this.state.timer}s | Streak: ${this.state.streak}`, 400, 50);
        }

        // Draw Code Drop Question
        if (this.type === 'code_drop' && !this.completed) {
            ctx.fillStyle = '#fff'; ctx.font = '20px Space Grotesk'; ctx.textAlign = 'center';
            this.wrapText(ctx, this.state.currentQuestion || "Drag the correct code:", 400, 80, 600, 30);
        }

        // Draw Items
        this.items.forEach(it => {
            if (it.type.includes('node')) {
                ctx.beginPath(); ctx.arc(it.x, it.y, it.r, 0, Math.PI*2);
                ctx.fillStyle = it.connectedTo ? this.colors.emerald : this.colors.violet;
                ctx.fill(); ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
                ctx.fillStyle = '#fff'; ctx.font = '14px Inter';
                ctx.textAlign = it.type === 'node_L' ? 'right' : 'left';
                ctx.fillText(it.text, it.x + (it.type === 'node_L' ? -30 : 30), it.y + 5);
                return;
            }

            ctx.fillStyle = it.color || this.colors.cardBg;
            if (it.isDragging) ctx.shadowBlur = 15; ctx.shadowColor = this.colors.violet;
            this.roundRect(ctx, it.x, it.y, it.w, it.h, 10); ctx.fill();
            ctx.strokeStyle = it.accent || this.colors.violet; ctx.lineWidth = 1; ctx.stroke();
            ctx.shadowBlur = 0;
            
            ctx.fillStyle = '#fff'; ctx.font = '14px Inter'; ctx.textAlign = 'center';
            this.wrapText(ctx, it.text, it.x + it.w/2, it.y + it.h/2 + 5, it.w - 10, 18);
        });
    }

    roundRect(ctx, x, y, w, h, r) {
        ctx.beginPath(); ctx.moveTo(x+r, y); ctx.lineTo(x+w-r, y); ctx.quadraticCurveTo(x+w, y, x+w, y+r);
        ctx.lineTo(x+w, y+h-r); ctx.quadraticCurveTo(x+w, y+h, x+w-r, y+h); ctx.lineTo(x+r, y+h);
        ctx.quadraticCurveTo(x, y+h, x, y+h-r); ctx.lineTo(x, y+r); ctx.quadraticCurveTo(x, y, x+r, y); ctx.closePath();
    }

    wrapText(ctx, text, x, y, maxWidth, lineHeight) {
        const words = text.split(' ');
        let line = '';
        let lines = [];
        for (let n = 0; n < words.length; n++) {
            let testLine = line + words[n] + ' ';
            if (ctx.measureText(testLine).width > maxWidth && n > 0) {
                lines.push(line); line = words[n] + ' ';
            } else { line = testLine; }
        }
        lines.push(line);
        lines.forEach((l, i) => ctx.fillText(l, x, y + (i * lineHeight) - (lines.length * lineHeight / 2)));
    }

    spawnConfetti(x, y) {
        confetti({ particleCount: 40, spread: 50, origin: { x: x / window.innerWidth, y: y / window.innerHeight } });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.engineApp = new NeuroLearnGameEngine('game-canvas');
});
