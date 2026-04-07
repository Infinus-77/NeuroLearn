// ================================================================
// STUDY BATTLE — Simulated Video Meet + Quiz Battle
// Simulates full P2P meet experience with an animated bot opponent
// No Firebase. No PeerJS. Pure local simulation.
// ================================================================

const CONFIG = window.BATTLE_CONFIG || {};

// ── State ─────────────────────────────────────────────────────
let currentRoomCode = null;
let curriculum      = null;
let currentRoundIdx = 0;
let myScore         = 0;
let botScore        = 0;
let roundTimer      = null;
let timerLeft       = 30;
let pollInterval    = null;
let botThinkTimer   = null;
let botLastScore    = 0;
let botName         = 'NeuroBot 🤖';
let isQuizRound     = false;
let botAnsweredFlag = false;
let meetStartTime   = null;
let meetDurInterval = null;
let camActive       = false;

// ── DOM ───────────────────────────────────────────────────────
const $  = id => document.getElementById(id);
const qs = s  => document.querySelector(s);

// ── INIT ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  showView('lobby');
  bindLobby();
  buildBotBooks();
});

function showView(name) {
  document.querySelectorAll('.battle-view').forEach(v => v.classList.add('hidden'));
  const el = $('view-' + name);
  if (el) el.classList.remove('hidden');
}

function buildBotBooks() {
  // Decorative bookshelf in bot's background
  const colors = ['#4c1d95','#1e3a5f','#064e3b','#7c2d12','#1e1b4b','#3b0764','#0f766e'];
  const heights = [38,52,44,60,36,48,55,40,50];
  const shelf = $('bot-books');
  if (!shelf) return;
  heights.forEach((h, i) => {
    const b = document.createElement('div');
    b.className = 'book';
    b.style.height = h + 'px';
    b.style.background = colors[i % colors.length];
    shelf.appendChild(b);
  });
}

// ── LOBBY ─────────────────────────────────────────────────────
function bindLobby() {
  $('btn-create-room')?.addEventListener('click', handleCreate);

  document.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const raw = chip.textContent.trim().replace(/^[^\w]+/, '');
      const inp = $('battle-topic');
      if (inp) { inp.value = raw; inp.focus(); }
    });
  });

  $('battle-topic')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') handleCreate();
  });

  // Webcam toggle button in controls
  $('ctrl-cam')?.addEventListener('click', toggleCam);
  $('ctrl-mic')?.addEventListener('click', () => {
    $('ctrl-mic').classList.toggle('active');
    $('mic-indicator').style.display = $('ctrl-mic').classList.contains('active') ? 'flex' : 'none';
  });
}

async function handleCreate() {
  const topic    = $('battle-topic')?.value.trim();
  const duration = parseInt($('battle-duration')?.value || '30');
  if (!topic) { showErr('Please enter a topic first!'); return; }

  const btn = $('btn-create-room');
  btn.disabled = true;
  $('btn-create-text').classList.add('hidden');
  $('btn-create-spinner').classList.remove('hidden');

  try {
    const res  = await fetch('/api/battle/create-room', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ topic, duration })
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    currentRoomCode = data.roomCode;
    curriculum      = data.curriculum;
    botName         = data.botName || 'NeuroBot 🤖';

    // Populate UI names
    const myDisplay = CONFIG.displayName || CONFIG.username || 'You';
    $('my-name').textContent    = myDisplay;
    $('opp-name').textContent   = botName.replace(' 🤖','');
    $('my-tile-name').textContent = myDisplay;
    $('bot-tile-name').textContent = botName;
    $('topic-label').textContent = '📚 ' + data.topic;

    const total = (curriculum.rounds?.length || 0) + 1;
    $('round-progress').textContent = 'Round 1 of ' + total;

    showView('battle');
    startMeetSession();
    startBattle(curriculum);

  } catch (err) {
    showErr('Error: ' + err.message);
    btn.disabled = false;
    $('btn-create-text').classList.remove('hidden');
    $('btn-create-spinner').classList.add('hidden');
  }
}

function showErr(msg) {
  const el = $('create-error');
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 5000);
}

// ── WEBCAM ────────────────────────────────────────────────────
async function toggleCam() {
  if (camActive) {
    const vid = $('my-video');
    if (vid.srcObject) vid.srcObject.getTracks().forEach(t => t.stop());
    vid.style.display = 'none';
    $('cam-placeholder').style.display = 'flex';
    $('ctrl-cam').classList.remove('active');
    camActive = false;
  } else {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      const vid = $('my-video');
      vid.srcObject = stream;
      vid.style.display = 'block';
      $('cam-placeholder').style.display = 'none';
      $('ctrl-cam').classList.add('active');
      camActive = true;
      addChatMsg('System', '📷 Camera connected', false);
    } catch (e) {
      addChatMsg('System', '📵 Camera unavailable', false);
    }
  }
}

// Try to auto-start camera when battle begins
async function tryAutoCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    const vid = $('my-video');
    vid.srcObject = stream;
    vid.style.display = 'block';
    $('cam-placeholder').style.display = 'none';
    $('ctrl-cam').classList.add('active');
    camActive = true;
  } catch (e) {
    // silently fall back to placeholder — camera permission not granted
  }
}

// ── MEET SESSION ──────────────────────────────────────────────
function startMeetSession() {
  meetStartTime = Date.now();
  meetDurInterval = setInterval(updateMeetDuration, 1000);
  tryAutoCamera();
  addChatMsg(botName.replace(' 🤖',''), "Let's do this! I've been studying 📚", true);
}

function updateMeetDuration() {
  if (!meetStartTime) return;
  const s = Math.floor((Date.now() - meetStartTime) / 1000);
  const m = Math.floor(s / 60).toString().padStart(2,'0');
  const sec = (s % 60).toString().padStart(2,'0');
  const el = $('meet-duration');
  if (el) el.textContent = m + ':' + sec;
}

function addChatMsg(sender, msg, isBot) {
  const chat = $('meet-chat');
  if (!chat) return;
  const div = document.createElement('div');
  div.className = 'chat-msg' + (isBot ? ' bot' : '');
  div.innerHTML = '<span class="sender">' + sender + ':</span> ' + msg;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;

  // Keep max 8 messages
  while (chat.children.length > 8) chat.removeChild(chat.firstChild);
}

// ── BOT EXPRESSIONS ───────────────────────────────────────────
const BOT_FACES = {
  focused:   '🤖',
  thinking:  '🤔',
  excited:   '🤩',
  correct:   '😄',
  wrong:     '😬',
  reading:   '📖',
  listening: '👂',
};

const BOT_CHAT_CORRECT = [
  "Yes! Got it! 🎉", "Easy one 😎", "I knew that!", "+points! Let's go!", "On fire today 🔥"
];
const BOT_CHAT_WRONG = [
  "Ugh, I messed up 😅", "Tricky question...", "Next one! I'll get it", "Hmm, didn't see that coming"
];
const BOT_CHAT_LEARN = [
  "Interesting! 🤓", "Taking notes...", "Oh wow, didn't know that!", "Cool fact 💡"
];
const BOT_CHAT_QUIZ = [
  "Okay thinking... 🤔", "Hmm let me think", "I know this one!", "Reading carefully..."
];

function setBotExpression(state) {
  const head    = $('bot-head');
  const scene   = $('bot-scene');
  const statusEl = $('bot-status-text');
  const emotionEl = $('emotion-label');
  const dotEl    = $('emotion-dot');

  if (head) head.textContent = BOT_FACES[state] || '🤖';

  // Remove previous expression classes
  ['expr-thinking','expr-correct','expr-wrong'].forEach(c => scene?.classList.remove(c));

  if (state === 'thinking') {
    scene?.classList.add('expr-thinking');
    if (statusEl) statusEl.textContent = 'Thinking...';
    if (emotionEl) emotionEl.textContent = 'Bot is thinking...';
    if (dotEl) dotEl.style.background = '#fbbf24';
    showTypingDots(true);
  } else if (state === 'correct') {
    scene?.classList.add('expr-correct');
    if (statusEl) statusEl.textContent = 'Got it right!';
    if (emotionEl) emotionEl.textContent = 'Bot is excited!';
    if (dotEl) dotEl.style.background = '#22c55e';
    showTypingDots(false);
    showReaction('🎉');
  } else if (state === 'wrong') {
    scene?.classList.add('expr-wrong');
    if (statusEl) statusEl.textContent = 'Oops...';
    if (emotionEl) emotionEl.textContent = 'Bot got it wrong';
    if (dotEl) dotEl.style.background = '#f97316';
    showTypingDots(false);
    showReaction('😬');
  } else if (state === 'reading') {
    if (statusEl) statusEl.textContent = 'Reading...';
    if (emotionEl) emotionEl.textContent = 'Bot is reading';
    if (dotEl) dotEl.style.background = '#60a5fa';
    showTypingDots(false);
  } else if (state === 'excited') {
    if (statusEl) statusEl.textContent = 'Ready!';
    if (emotionEl) emotionEl.textContent = 'Bot is excited!';
    if (dotEl) dotEl.style.background = '#a78bfa';
    showTypingDots(false);
    showReaction('⚡');
  } else {
    if (statusEl) statusEl.textContent = 'Focused';
    if (emotionEl) emotionEl.textContent = 'Bot is focused';
    if (dotEl) dotEl.style.background = '#22c55e';
    showTypingDots(false);
  }
}

function showTypingDots(show) {
  const el = $('typing-dots');
  if (el) el.classList.toggle('show', show);
}

function showReaction(emoji) {
  const el = $('bot-reaction');
  if (!el) return;
  el.textContent = emoji;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2000);
}

// Active speaker highlight
function setActiveSpeaker(who) {
  $('my-video-tile')?.classList.remove('active-speaker');
  $('bot-video-tile')?.classList.remove('active-speaker');
  if (who === 'me')  $('my-video-tile')?.classList.add('active-speaker');
  if (who === 'bot') $('bot-video-tile')?.classList.add('active-speaker');
}

// ── POLLING ───────────────────────────────────────────────────
function startPolling() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(pollBot, 1100);
}

function stopPolling() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

async function pollBot() {
  if (!currentRoomCode) return;
  try {
    const res  = await fetch('/api/battle/state/' + currentRoomCode);
    const data = await res.json();
    if (data.error) return;

    if (data.botScore !== botLastScore) {
      const gained = data.botScore - botLastScore;
      botScore     = data.botScore;
      botLastScore = botScore;
      animateBotScore(botScore);

      if (isQuizRound && !botAnsweredFlag) {
        botAnsweredFlag = true;
        const wasCorrect = gained > 0;
        setBotExpression(wasCorrect ? 'correct' : 'wrong');
        setActiveSpeaker('bot');
        const msgs = wasCorrect ? BOT_CHAT_CORRECT : BOT_CHAT_WRONG;
        addChatMsg(botName.replace(' 🤖',''), msgs[Math.floor(Math.random()*msgs.length)], true);
        // Reset after 2s
        setTimeout(() => { setBotExpression('focused'); setActiveSpeaker(null); }, 2500);
      }
    }
  } catch(e) {}
}

// ── BOT THINK TIMER ───────────────────────────────────────────
function startBotThink(roundIndex) {
  if (botThinkTimer) clearTimeout(botThinkTimer);
  botAnsweredFlag = false;
  const delay = (5 + Math.floor(Math.random() * 17)) * 1000;

  // Start thinking immediately
  setBotExpression('thinking');
  setActiveSpeaker('bot');
  const chatMsgs = BOT_CHAT_QUIZ;
  addChatMsg(botName.replace(' 🤖',''), chatMsgs[Math.floor(Math.random()*chatMsgs.length)], true);

  botThinkTimer = setTimeout(() => {
    // Notify server this round started so it can calculate bot answer
    fetch('/api/battle/start-round', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ roomCode: currentRoomCode, roundIndex })
    }).catch(()=>{});
  }, delay);
}

// ── SCORE ANIMATION ───────────────────────────────────────────
function animateScore(elId, score) {
  const el = $(elId);
  if (!el) return;
  el.textContent = score;
  el.classList.remove('pop');
  void el.offsetWidth; // reflow
  el.classList.add('pop');
  setTimeout(() => el.classList.remove('pop'), 300);
}
function animateBotScore(score) {
  animateScore('opp-score', score);
  const el = $('opp-score');
  if (el) el.textContent = score;
}

// ── BATTLE ENGINE ─────────────────────────────────────────────
function startBattle(currData) {
  curriculum    = currData;
  currentRoundIdx = 0;
  myScore = 0; botScore = 0; botLastScore = 0;
  animateScore('my-score', 0);
  animateBotScore(0);
  startPolling();
  showRound(0);
}

function showRound(idx) {
  clearTimer();
  isQuizRound = false;
  $('quiz-result')?.classList.add('hidden');

  const allRounds = curriculum.rounds || [];
  const totalR    = allRounds.length + 1;
  $('round-progress').textContent = 'Round ' + (idx+1) + ' of ' + totalR;

  let round, isFinal = false;
  if (idx < allRounds.length) {
    round = allRounds[idx];
  } else if (idx === allRounds.length) {
    round = Object.assign({}, curriculum.finalChallenge, { type:'quiz', roundNumber: idx+1 });
    isFinal = true;
  } else {
    endBattle(); return;
  }

  $('round-label').textContent = isFinal ? '⚡ Final Boss!' : 'Round '+(round.roundNumber||idx+1)+' of '+totalR;

  if (round.type === 'learn') showLearn(round);
  else                        showQuiz(round, idx);
}

// ── LEARN CARD ────────────────────────────────────────────────
function showLearn(round) {
  $('learn-card')?.classList.remove('hidden');
  $('quiz-card')?.classList.add('hidden');
  const timer = $('battle-timer');
  if (timer) { timer.textContent = '📖 Study'; timer.style.color = '#60a5fa'; }

  $('learn-title').textContent   = round.title || '';
  $('learn-content').textContent = round.content || '';
  const ff = $('learn-funfact');
  if (ff) {
    if (round.funFact) { ff.textContent = '💡 ' + round.funFact; ff.classList.remove('hidden'); }
    else                               { ff.classList.add('hidden'); }
  }

  setBotExpression('reading');
  setActiveSpeaker(null);
  addChatMsg(botName.replace(' 🤖',''), BOT_CHAT_LEARN[Math.floor(Math.random()*BOT_CHAT_LEARN.length)], true);

  // Bot "talks" after a few seconds as if discussing content
  setTimeout(() => {
    if (isQuizRound) return; // already moved on
    setBotExpression('excited');
    setActiveSpeaker('bot');
    addChatMsg(botName.replace(' 🤖',''), 'Ready when you are!', true);
    setTimeout(() => setActiveSpeaker(null), 2000);
  }, 4000 + Math.random()*3000);

  const btn = $('btn-ready');
  const newBtn = btn.cloneNode(true);
  btn.parentNode.replaceChild(newBtn, btn);
  newBtn.addEventListener('click', () => {
    currentRoundIdx++;
    showRound(currentRoundIdx);
  });
}

// ── QUIZ CARD ─────────────────────────────────────────────────
async function showQuiz(round, roundIdx) {
  $('learn-card')?.classList.add('hidden');
  $('quiz-card')?.classList.remove('hidden');
  $('quiz-result')?.classList.add('hidden');
  isQuizRound = true;
  botAnsweredFlag = false;

  $('quiz-question').textContent = round.question || '';

  const grid = $('quiz-options');
  grid.innerHTML = '';
  (round.options || []).forEach((opt, i) => {
    const btn = document.createElement('button');
    btn.className = 'opt-btn';
    btn.textContent = opt;
    const letter = String.fromCharCode(65 + i);
    btn.dataset.letter = letter;
    btn.addEventListener('click', () => submitAnswer(btn, round, letter, roundIdx), { once:true });
    grid.appendChild(btn);
  });

  // Notify server + start bot
  try {
    await fetch('/api/battle/start-round', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ roomCode: currentRoomCode, roundIndex: roundIdx })
    });
  } catch(e) {}

  startBotThink(roundIdx);

  // Player timer
  timerLeft = 30;
  updateTimer(timerLeft);
  roundTimer = setInterval(() => {
    timerLeft--;
    updateTimer(timerLeft);
    if (timerLeft <= 0) {
      clearTimer();
      document.querySelectorAll('.opt-btn').forEach(b => {
        b.disabled = true;
        if (b.dataset.letter === round.correctAnswer) b.classList.add('correct');
      });
      notifyAnswer(roundIdx, 0);
      showResult(false, round, null, 0);
    }
  }, 1000);
}

function updateTimer(s) {
  const el = $('battle-timer');
  if (!el) return;
  el.textContent = '⏱ ' + Math.max(0,s) + 's';
  el.style.color = s <= 10 ? '#f87171' : '#fbbf24';
}

function clearTimer() {
  if (roundTimer) { clearInterval(roundTimer); roundTimer = null; }
}

function submitAnswer(btn, round, letter, roundIdx) {
  clearTimer();
  if (botThinkTimer) clearTimeout(botThinkTimer);

  document.querySelectorAll('.opt-btn').forEach(b => b.disabled = true);

  const correct   = letter === round.correctAnswer;
  const timeBonus = correct ? Math.max(0, Math.floor(timerLeft * 3)) : 0;
  const base      = round.points || 100;
  const earned    = correct ? base + timeBonus : 0;

  document.querySelectorAll('.opt-btn').forEach(b => {
    if (b.dataset.letter === round.correctAnswer) b.classList.add('correct');
  });
  if (!correct) btn.classList.add('wrong');

  myScore += earned;
  animateScore('my-score', myScore);
  setActiveSpeaker('me');
  notifyAnswer(roundIdx, earned);
  showResult(correct, round, letter, earned);

  // Player chat reaction
  setTimeout(() => {
    addChatMsg('You', correct ? 'Got it! 🙌' : 'Ugh, wrong one...', false);
    setActiveSpeaker(null);
  }, 500);
}

async function notifyAnswer(roundIdx, earned) {
  try {
    await fetch('/api/battle/state/' + currentRoomCode, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ roundIndex: roundIdx, earnedPoints: earned })
    });
  } catch(e) {}
}

function showResult(correct, round, selected, earned) {
  const box = $('quiz-result');
  if (box) box.classList.remove('hidden');
  $('qr-icon').textContent = correct ? '✅' : '❌';
  $('qr-text').textContent = correct
    ? 'Correct! +' + earned + ' points (includes speed bonus!)'
    : (selected ? 'Wrong. Answer was ' + round.correctAnswer + '.' : "Time's up! Answer was " + round.correctAnswer + '.');
  $('qr-expl').textContent = round.explanation || '';

  setTimeout(() => { currentRoundIdx++; showRound(currentRoundIdx); }, 3500);
}

// ── END BATTLE ────────────────────────────────────────────────
async function endBattle() {
  clearTimer();
  stopPolling();
  if (botThinkTimer) clearTimeout(botThinkTimer);
  if (meetDurInterval) clearInterval(meetDurInterval);

  // Final score fetch
  try {
    const res  = await fetch('/api/battle/state/' + currentRoomCode);
    const data = await res.json();
    if (!data.error) { botScore = data.botScore || 0; botName = data.botName || botName; }
  } catch(e) {}

  try {
    await fetch('/api/battle/end', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ roomCode: currentRoomCode })
    });
  } catch(e) {}

  const myName = CONFIG.displayName || CONFIG.username || 'You';
  const iWon   = myScore > botScore;
  const tied   = myScore === botScore;

  // Bot reacts to end
  setBotExpression(iWon ? 'wrong' : 'correct');
  addChatMsg(botName.replace(' 🤖',''),
    tied ? "Tie! Good game! 🤝" : (iWon ? "Congrats, you beat me! 🙏" : "Haha I win! Rematch? 😄"), true);

  $('result-trophy').textContent = tied ? '🤝' : (iWon ? '🏆' : '🎖️');
  $('result-title').textContent  = tied ? "It's a Tie! 🤝" : (iWon ? 'You Won! 🏆' : botName + ' Wins!');

  $('final-scores').innerHTML =
    '<div class="final-row ' + (iWon||tied?'winner':'') + '">' +
      '<span>' + myName + '</span><span class="final-pts">' + myScore + ' pts</span></div>' +
    '<div class="final-row ' + (!iWon&&!tied?'winner':'') + '">' +
      '<span>' + botName + '</span><span class="final-pts">' + botScore + ' pts</span></div>';

  setTimeout(() => {
    const r = $('battle-results');
    if (r) r.classList.remove('hidden');
  }, 2000); // small delay so bot reaction is visible first
}
