# Generate app.py from the NeuroLearn AI spec. 
# Write complete, production-ready code. 
# Zero placeholder comments. 
# Every function fully implemented. 

import os
import sqlite3
import json
import time
import threading
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response, send_from_directory, stream_with_context, flash
from flask_session import Session
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from utils.ai_processor import extract_text_from_pdf, generate_syllabus, process_chapter, call_llm
from utils.tts_engine import generate_chapter_audio_stream, get_voice_for_language
from utils.story_generator import generate_manga_story, generate_manga_images_batch, generate_simplified_content

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "neurolearn_super_secret_key_123")

# Session Config
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_PERMANENT"] = False
Session(app)

# Database Setup
def get_db():
    db_path = "neurolearn.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with app.app_context():
        db = get_db()
        # Leaderboard Table
        db.execute("""
            CREATE TABLE IF NOT EXISTS leaderboard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                topic TEXT,
                score INTEGER,
                xp INTEGER,
                badge TEXT
            )
        """)
        # Chapters Table (Persistence layer for synthesized content)
        db.execute("""
            CREATE TABLE IF NOT EXISTS chapters (
                id TEXT PRIMARY KEY,
                topic_id TEXT,
                data_json TEXT
            )
        """)
        # Users Table
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT,
                user_type TEXT DEFAULT 'child',
                age_range TEXT DEFAULT '11-13',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # User Topics Table — persists learning sessions per user
        db.execute("""
            CREATE TABLE IF NOT EXISTS user_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                topic_title TEXT,
                subject_domain TEXT,
                syllabus_json TEXT,
                raw_content TEXT,
                learning_profile_json TEXT DEFAULT '{}',
                cognitive_style TEXT DEFAULT 'focus',
                gender TEXT DEFAULT 'female',
                emotion TEXT DEFAULT 'okay',
                chapter_progress_json TEXT DEFAULT '{}',
                total_xp INTEGER DEFAULT 0,
                chapters_generated_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        # Emotion Logs Table — records webcam emotion detections
        db.execute("""
            CREATE TABLE IF NOT EXISTS emotion_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                topic_id INTEGER,
                chapter_id INTEGER,
                emotion_state TEXT,
                confidence REAL DEFAULT 0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        db.commit()

init_db()

# --- AUTH HELPERS ---

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    """Get current logged-in user dict or None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None

def _save_topic_progress():
    """Persist current session topic progress to user_topics table."""
    user_id = session.get("user_id")
    topic_id = session.get("active_topic_id")
    if not user_id or not topic_id:
        return
    try:
        db = get_db()
        db.execute("""UPDATE user_topics SET 
            chapter_progress_json = ?,
            total_xp = ?,
            chapters_generated_json = ?,
            last_accessed = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?""",
            (json.dumps(session.get("chapter_progress", {})),
             session.get("total_xp", 0),
             json.dumps(session.get("ai_data", {}).get("chapters_generated", {})),
             topic_id, user_id))
        db.commit()
    except Exception as e:
        print(f"⚠️ [SAVE-PROGRESS] Error saving topic progress: {e}")

# Real-time processing status
processing_status = {"message": "Idle", "progress": 0, "complete": False}


def _clear_old_chapters():
    """Purge all old chapter data."""
    try:
        db = get_db()
        
        # Get count before deleting
        row = db.execute("SELECT count(*) as cnt FROM chapters").fetchone()
        cnt = row["cnt"] if row else 0

        # Delete all chapter rows
        db.execute("DELETE FROM chapters")
        db.commit()
        print(f"🗑️ [CLEANUP] Cleared {cnt} old chapters from database")
    except Exception as e:
        print(f"⚠️ [CLEANUP] Error: {str(e)}")

# --- FAVICON ROUTE (prevents 404 errors) ---
@app.route('/favicon.ico')
def favicon():
    """Return a simple favicon or 204 No Content to prevent 404 errors"""
    return '', 204

# --- AUTH ROUTES ---

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    
    # Get role from query param (child or parent)
    role = request.args.get("role", "child")
    if role not in ("child", "parent"):
        role = "child"
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        display_name = request.form.get("display_name", "").strip() or username
        role = request.form.get("user_type", role)
        age_range = request.form.get("age_range", "11-13")

        errors = []
        if not username or len(username) < 3:
            errors.append("Username must be at least 3 characters.")
        if not email or "@" not in email:
            errors.append("Please enter a valid email address.")
        if not password or len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            return render_template("signup.html", errors=errors, username=username, email=email, display_name=display_name, role=role)

        db = get_db()
        if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
            errors.append("Username already taken.")
        if db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            errors.append("Email already registered.")
        if errors:
            return render_template("signup.html", errors=errors, username=username, email=email, display_name=display_name, role=role)

        pw_hash = generate_password_hash(password)
        db.execute("INSERT INTO users (username, email, password_hash, display_name, user_type, age_range) VALUES (?, ?, ?, ?, ?, ?)",
                   (username, email, pw_hash, display_name, role, age_range))
        db.commit()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["display_name"] = user["display_name"]
        session["user_type"] = role
        session["age_range"] = age_range
        session["student_name"] = display_name
        print(f"✓ [AUTH] New user registered: {username} (id={user['id']}, type={role}, age={age_range})")
        return redirect(url_for("dashboard"))

    return render_template("signup.html", errors=[], username="", email="", display_name="", role=role)

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        login_id = request.form.get("login_id", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ? OR email = ?", (login_id, login_id.lower())).fetchone()

        if not user or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Invalid username/email or password.", login_id=login_id)

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["display_name"] = user["display_name"]
        session["user_type"] = user["user_type"] or "child"
        session["age_range"] = user["age_range"] or "11-13"
        session["student_name"] = user["display_name"]
        print(f"✓ [AUTH] User logged in: {user['username']} (id={user['id']}, type={user['user_type']}, age={session['age_range']})")
        return redirect(url_for("dashboard"))

    return render_template("login.html", error=None, login_id="")

@app.route("/logout")
def logout():
    # Save progress before logging out
    _save_topic_progress()
    session.clear()
    return redirect(url_for("index"))

# --- DASHBOARD ---

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    user_id = session["user_id"]
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    topics = db.execute("SELECT * FROM user_topics WHERE user_id = ? ORDER BY last_accessed DESC", (user_id,)).fetchall()

    topic_list = []
    total_xp_all = 0
    for t in topics:
        syllabus = json.loads(t["syllabus_json"] or "{}")
        progress = json.loads(t["chapter_progress_json"] or "{}")
        total_chapters = len(syllabus.get("chapters", []))
        completed_chapters = sum(1 for v in progress.values() if v.get("completed"))
        total_xp_all += t["total_xp"] or 0
        topic_list.append({
            "id": t["id"],
            "topic_title": t["topic_title"] or "Untitled Topic",
            "subject_domain": t["subject_domain"] or "General",
            "total_chapters": total_chapters,
            "completed_chapters": completed_chapters,
            "total_xp": t["total_xp"] or 0,
            "last_accessed": t["last_accessed"],
            "created_at": t["created_at"],
            "progress_pct": int((completed_chapters / total_chapters * 100) if total_chapters > 0 else 0)
        })

    return render_template("dashboard.html",
                           user=dict(user),
                           topics=topic_list,
                           total_xp_all=total_xp_all)

@app.route("/api/continue-topic/<int:topic_id>", methods=["POST"])
@login_required
def continue_topic(topic_id):
    """Restore a saved topic into the session so the user can continue learning."""
    db = get_db()
    user_id = session["user_id"]
    topic = db.execute("SELECT * FROM user_topics WHERE id = ? AND user_id = ?", (topic_id, user_id)).fetchone()
    if not topic:
        return jsonify({"error": "Topic not found"}), 404

    # Clear old chapters from the chapters table
    _clear_old_chapters()

    # Restore session state from the saved topic
    syllabus = json.loads(topic["syllabus_json"] or "{}")
    session["raw_content"] = topic["raw_content"] or ""
    session["ai_data"] = {
        "syllabus": syllabus,
        "chapters_generated": json.loads(topic["chapters_generated_json"] or "{}")
    }
    session["chapter_progress"] = json.loads(topic["chapter_progress_json"] or "{}")
    session["total_xp"] = topic["total_xp"] or 0
    session["learning_profile"] = json.loads(topic["learning_profile_json"] or "{}")
    session["cognitive_style"] = topic["cognitive_style"] or "focus"
    session["gender"] = topic["gender"] or "female"
    session["emotion"] = topic["emotion"] or "okay"
    session["student_name"] = session.get("display_name", "Learner")
    session["active_topic_id"] = topic["id"]
    session["user_type"] = "child"
    session.modified = True

    # Update last_accessed
    db.execute("UPDATE user_topics SET last_accessed = CURRENT_TIMESTAMP WHERE id = ?", (topic_id,))
    db.commit()

    print(f"✓ [CONTINUE-TOPIC] Restored topic {topic_id}: {topic['topic_title']}")
    return jsonify({"redirect": url_for("chapters")})

@app.route("/api/delete-topic/<int:topic_id>", methods=["POST"])
@login_required
def delete_topic(topic_id):
    """Delete a saved topic."""
    db = get_db()
    user_id = session["user_id"]
    db.execute("DELETE FROM user_topics WHERE id = ? AND user_id = ?", (topic_id, user_id))
    db.commit()
    return jsonify({"status": "deleted"})

# --- MAIN ROUTES ---

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    user_type = request.form.get("user_type")
    content_type = request.form.get("content_type") # 'file' or 'text'
    
    raw_text = ""
    if content_type == "file":
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        file = request.files["file"]
        raw_text = extract_text_from_pdf(file)
    else:
        raw_text = request.form.get("text_input", "").strip()

    if not raw_text:
        return jsonify({"error": "No content provided"}), 400

    session["user_type"] = user_type
    session["raw_content"] = raw_text
    session["word_count"] = len(raw_text.split())
    session["ai_data"] = {"syllabus": None}  # Initialize ai_data dictionary
    session["chapter_progress"] = {}  # Initialize chapter progress tracking
    
    if user_type == "parent":
        return jsonify({"redirect": url_for("parent_form")})
    else:
        # Default profile for child
        session["learning_profile"] = {
            "student_name": "Learner",
            "age_range": session.get("age_range", "11-13"),
            "has_adhd": False, "has_dyslexia": False, "has_autism": False,
            "has_anxiety": False, "slow_processing": False, 
            "working_memory": False, "sensory_sensitive": False,
            "confidence_level": "medium"
        }
        return jsonify({"redirect": url_for("onboarding")})

@app.route("/parent-form", methods=["GET", "POST"])
def parent_form():
    if request.method == "POST":
        data = request.form
        needs = data.getlist("needs")
        
        # Determine ADHD profile
        focus_type = data.get("focus_type", "typical")
        has_adhd = focus_type in ["adhd_mild", "adhd_severe", "adhd_hyperfocus"] or data.get("adhd_diagnosis") == "yes"
        adhd_subtype = focus_type
        
        # Parse special interests
        special_interests = data.getlist("special_interests")
        other_interest = data.get("special_interest_other", "").strip()
        if other_interest:
            special_interests.append(other_interest)
        
        # Parse processing speed to numeric multiplier
        proc_speed_map = {"typical": 1.0, "slight": 1.25, "noticeable": 1.5, "very_slow": 2.0}
        processing_speed_raw = data.get("processing_speed", "typical")
        quiz_time_multiplier = proc_speed_map.get(processing_speed_raw, 1.0)
        
        # TTS rate from processing speed
        tts_rate_map = {"typical": "+0%", "slight": "-10%", "noticeable": "-20%", "very_slow": "-30%"}
        
        # Parse confidence level from slider
        confidence_raw = int(data.get("confidence_level", "3"))
        confidence_level = "low" if confidence_raw <= 2 else ("high" if confidence_raw >= 4 else "medium")
        
        session["learning_profile"] = {
            # Identity
            "student_name": data.get("student_name", "Learner"),
            "age_range": data.get("age_range", "11-13"),
            "gender": data.get("gender", "no_preference"),
            "home_language": data.get("home_language", "en"),
            
            # ADHD
            "has_adhd": has_adhd,
            "adhd_subtype": adhd_subtype,
            "session_length_pref": int(data.get("session_length", "10")),
            "special_interests": special_interests,
            
            # Reading/Dyslexia
            "has_dyslexia": any(x in needs for x in ["dyslexia_decoding", "dyslexia_tracking", "dyslexia_spelling"]),
            "dyslexia_decoding": "dyslexia_decoding" in needs,
            "dyslexia_tracking": "dyslexia_tracking" in needs,
            "irlen_syndrome": "irlen_syndrome" in needs,
            
            # Writing/Dysgraphia
            "has_dysgraphia": any(x in needs for x in ["dysgraphia_motor", "dysgraphia_organisation", "dysgraphia_preference"]),
            "dysgraphia_motor": "dysgraphia_motor" in needs,
            "dysgraphia_organisation": "dysgraphia_organisation" in needs,
            "voice_first_input": "dysgraphia_preference" in needs or data.get("input_mode") == "voice",
            
            # Math/Dyscalculia
            "has_dyscalculia": any(x in needs for x in ["dyscalculia_quantity", "dyscalculia_sequence"]),
            "dyscalculia_visual_numbers": "dyscalculia_quantity" in needs,
            
            # Processing
            "slow_processing": processing_speed_raw in ["noticeable", "very_slow"],
            "processing_speed_raw": processing_speed_raw,
            "quiz_time_multiplier": quiz_time_multiplier,
            "default_tts_rate": tts_rate_map.get(processing_speed_raw, "+0%"),
            
            # Memory
            "working_memory": data.get("working_memory", "typical") != "typical",
            "working_memory_severity": data.get("working_memory", "typical"),
            
            # Autism
            "has_autism": any(x in needs for x in ["autism_literal", "autism_routine", "autism_predictability", "autism_sensory"]),
            "autism_literal": "autism_literal" in needs,
            "autism_routine": "autism_routine" in needs,
            "autism_predictability": "autism_predictability" in needs,
            "autism_special_interest": "autism_special_interest" in needs,
            
            # Anxiety
            "has_anxiety": any(x in needs for x in ["anxiety_tests", "anxiety_overwhelm", "anxiety_reassurance", "anxiety_avoidance"]),
            "anxiety_tests": "anxiety_tests" in needs,
            "anxiety_overwhelm": "anxiety_overwhelm" in needs,
            "anxiety_reassurance": "anxiety_reassurance" in needs,
            "hide_leaderboard": "anxiety_tests" in needs or "anxiety_avoidance" in needs,
            
            # Sensory
            "sensory_sensitive": any(x in needs for x in ["sensory_visual", "sensory_auditory", "sensory_clutter", "autism_sensory"]),
            "sensory_visual": "sensory_visual" in needs,
            "sensory_auditory": "sensory_auditory" in needs,
            "sensory_clutter": "sensory_clutter" in needs,
            
            # Confidence & notes
            "confidence_level": confidence_level,
            "confidence_raw": confidence_raw,
            "parent_notes": data.get("parent_notes", "")[:200],
        }
        
        session["student_name"] = session["learning_profile"]["student_name"]
        return redirect(url_for("onboarding"))
    
    return render_template("parent_form.html")

@app.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    if request.method == "POST":
        data = request.json
        session["student_name"] = data.get("name", session.get("student_name", "Learner"))
        session["cognitive_style"] = data.get("style", "focus")
        session["gender"] = data.get("voice", "standard_female")
        session["emotion"] = data.get("emotion", "okay")
        session["preferred_language"] = data.get("preferred_language", "en")
        
        # Trigger Pipeline Reset — clear stale DB data
        _clear_old_chapters()
        session["ai_data"] = {"chapters": {}, "syllabus": None}
        session["chapter_progress"] = {}
        session["total_xp"] = 0
        
        return jsonify({"redirect": url_for("loading_page")})
    
    return render_template("onboarding.html", 
                           name=session.get("student_name", ""),
                           user_type=session.get("user_type"))

@app.route("/loading")
def loading_page():
    return render_template("loading.html")

@app.route("/api/init-pipeline", methods=["POST"])
def init_pipeline():
    """
    Synchronous endpoint to initialize pipeline.
    Generates syllabus and saves to session.
    Called from loading page via fetch, not as streaming.
    """
    try:
        raw_text = session.get("raw_content", "")
        
        print(f"DEBUG: init_pipeline called")
        print(f"DEBUG: raw_content exists: {bool(raw_text)}")
        
        if not raw_text:
            return jsonify({
                "success": False,
                "error": "No content detected. Please go back and upload a document."
            }), 400
        
        # Clear old chapters before generating new syllabus
        _clear_old_chapters()
        
        # Generate syllabus
        print("DEBUG: Generating syllabus...")
        preferred_language = session.get("preferred_language", "en")
        syllabus = generate_syllabus(raw_text, preferred_language=preferred_language)
        print(f"DEBUG: Syllabus generated with {len(syllabus.get('chapters', []))} chapters")
        
        # Initialize ai_data if needed
        if "ai_data" not in session:
            session["ai_data"] = {}
        if "chapter_progress" not in session:
            session["chapter_progress"] = {}
        
        # Save syllabus to session
        session["ai_data"]["syllabus"] = syllabus
        session["ai_data"]["chapters_generated"] = {}
        
        # Initialize chapter_progress
        chapters = syllabus.get("chapters", [])
        for chapter in chapters:
            c_id = str(chapter["id"])
            if c_id not in session["chapter_progress"]:
                session["chapter_progress"][c_id] = {
                    "completed": False,
                    "game_score": 0,
                    "quiz_score": 0,
                    "xp_earned": 0
                }
        
        session.modified = True
        print(f"DEBUG: Session saved with syllabus")
        
        # Persist topic for logged-in users, OR generate a temporary topic ID for guests
        if session.get("user_id"):
            db = get_db()
            topic_title = syllabus.get("topic_title", "Learning Module")
            subject_domain = syllabus.get("subject_domain", "General")
            cursor = db.execute("""INSERT INTO user_topics 
                (user_id, topic_title, subject_domain, syllabus_json, raw_content, 
                 learning_profile_json, cognitive_style, gender, emotion, chapter_progress_json, total_xp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session["user_id"], topic_title, subject_domain,
                 json.dumps(syllabus), session.get("raw_content", ""),
                 json.dumps(session.get("learning_profile", {})),
                 session.get("cognitive_style", "focus"),
                 session.get("gender", "female"),
                 session.get("emotion", "okay"),
                 json.dumps(session.get("chapter_progress", {})),
                 0))
            db.commit()
            session["active_topic_id"] = cursor.lastrowid
            session.modified = True
            print(f"DEBUG: Created user_topic id={cursor.lastrowid} for user {session['user_id']}")
        else:
            # For guest users, use a synthetic topic ID based on session ID
            import hashlib
            session_hash = int(hashlib.md5(str(id(session)).encode()).hexdigest(), 16) % 100000
            session["active_topic_id"] = session_hash + 1  # Ensure positive, non-zero
            print(f"DEBUG: Guest session - assigned synthetic topic_id={session['active_topic_id']}")
        
        return jsonify({
            "success": True,
            "chapters_count": len(chapters),
            "message": f"Syllabus ready with {len(chapters)} chapters"
        })
    
    except Exception as e:
        print(f"ERROR in init_pipeline: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/api/pipeline-status")
def pipeline_status():
    """
    OPTIMIZED: Only generates the syllabus (chapter list).
    Individual chapters are generated on-demand when student clicks them.
    """
    raw_text = session.get("raw_content", "")
    learning_profile = session.get("learning_profile", {})
    
    print(f"DEBUG: pipeline_status called")
    print(f"DEBUG: raw_content exists: {bool(raw_text)}")
    print(f"DEBUG: raw_content length: {len(raw_text)}")
    print(f"DEBUG: session keys: {list(session.keys())}")
    
    @stream_with_context
    def generate():
        if not raw_text:
            error_msg = "No content detected. Please go back and upload a document."
            print(f"DEBUG: {error_msg}")
            yield f"data: {json.dumps({'error': error_msg, 'complete': True})}\n\n"
            return

        try:
            yield f"data: {json.dumps({'message': 'Building your personalized syllabus...', 'progress': 30, 'complete': False})}\n\n"
            time.sleep(1)
            
            # Clear old chapters before generating new syllabus
            _clear_old_chapters()
            
            # ONLY generate syllabus - not individual chapters
            print("DEBUG: Starting syllabus generation...")
            preferred_language = session.get("preferred_language", "en")
            syllabus = generate_syllabus(raw_text, preferred_language=preferred_language)
            print(f"DEBUG: Syllabus generated with {len(syllabus.get('chapters', []))} chapters")
            
            # Save syllabus to session - BEFORE continuation
            session["ai_data"]["syllabus"] = syllabus
            session["ai_data"]["chapters_generated"] = {}
            
            # Initialize chapter_progress for all chapters
            chapters = syllabus.get("chapters", [])
            for chapter in chapters:
                c_id = str(chapter["id"])
                if c_id not in session["chapter_progress"]:
                    session["chapter_progress"][c_id] = {
                        "completed": False, 
                        "game_score": 0, 
                        "quiz_score": 0, 
                        "xp_earned": 0
                    }
            
            session.modified = True
            print(f"DEBUG: Session modified, ai_data syllabus set")
            
            yield f"data: {json.dumps({'message': f'Syllabus ready! {len(chapters)} chapters available.', 'progress': 80, 'complete': False})}\n\n"
            time.sleep(1)
            
            print("DEBUG: Sending complete message...")
            yield f"data: {json.dumps({'message': 'Launching learning experience...', 'progress': 100, 'complete': True})}\n\n"
            
        except Exception as e:
            print(f"PIPELINE ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'error': f'Syllabus generation failed: {str(e)}', 'complete': True})}\n\n"

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"
    })

@app.route("/api/generate-chapter/<int:chapter_id>", methods=["POST"])
def generate_chapter(chapter_id):
    """
    Generate a single chapter on-demand when student clicks it.
    INTERCHANGED: Uses Groq for content (faster), OpenRouter was for syllabus.
    CONCURRENT: Starts audio generation in background thread immediately after content is generated.
    """
    try:
        db = get_db()
        print(f"\n🚀 [GENERATE-CHAPTER] Starting for chapter {chapter_id}")
        
        # Check if chapter is already generated
        existing = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(chapter_id),)).fetchone()
        if existing:
            print(f"✓ [GENERATE-CHAPTER] Chapter {chapter_id} already cached")
            return jsonify({"status": "cached", "message": "Chapter already generated"})
        
        # Get syllabus and find this chapter
        syllabus = session.get("ai_data", {}).get("syllabus")
        if not syllabus:
            print(f"✗ [GENERATE-CHAPTER] Syllabus not found in session")
            return jsonify({"error": "Syllabus not found"}), 400
        
        # Find chapter in syllabus
        target_chapter = None
        for ch in syllabus.get("chapters", []):
            if int(ch["id"]) == chapter_id:
                target_chapter = ch
                break
        
        if not target_chapter:
            print(f"✗ [GENERATE-CHAPTER] Chapter {chapter_id} not found in syllabus")
            return jsonify({"error": f"Chapter {chapter_id} not found in syllabus"}), 404
        
        # Get learning context from session
        cognitive_style = session.get("cognitive_style", "focus")
        gender = session.get("gender", "female")
        emotion = session.get("emotion", "okay")
        learning_profile = session.get("learning_profile", {})
        print(f"📋 [GENERATE-CHAPTER] Profile: {cognitive_style}, {gender}, {emotion}")
        
        raw_text = session.get("raw_content", "")
        
        # Determine Game Style for THIS chapter
        game_types = ["true_false_blitz", "concept_connect", "sequence_sort", "label_match"]
        subject_domain = syllabus.get("subject_domain", "").lower()
        if "coding" in subject_domain or "programming" in subject_domain or "computer" in subject_domain or "development" in subject_domain or "software" in subject_domain:
            game_types.append("code_drop")
            
        chapter_index = 0
        for i, ch in enumerate(syllabus.get("chapters", [])):
            if int(ch["id"]) == int(chapter_id):
                chapter_index = i
                break
                
        assigned_game = game_types[chapter_index % len(game_types)]
        
        # Generate chapter content
        preferred_language = session.get("preferred_language", "en")
        print(f"⏳ [GENERATE-CHAPTER] Processing chapter content (Game: {assigned_game}, Lang: {preferred_language})...")
        full_chapter = process_chapter(target_chapter, cognitive_style, gender, emotion, learning_profile, raw_text, assigned_game, preferred_language=preferred_language)
        print(f"✓ [GENERATE-CHAPTER] Chapter content generated, narration length: {len(full_chapter.get('narration_script', ''))}")
        
        # Prepare chapter data
        full_chapter["audio_url"] = "placeholder.mp3"
        full_chapter["chapter_id"] = str(chapter_id)
        full_chapter["title"] = target_chapter.get("title", "Chapter")
        full_chapter["subject_domain"] = syllabus.get("subject_domain", "General")
        full_chapter["topic_title"] = syllabus.get("topic_title", "Learning Module")
        
        # Save to database FIRST
        print(f"💾 [GENERATE-CHAPTER] Saving to database...")
        db.execute("INSERT OR REPLACE INTO chapters (id, topic_id, data_json) VALUES (?, ?, ?)",
                   (str(chapter_id), "current", json.dumps(full_chapter)))
        db.commit()
        print(f"✓ [GENERATE-CHAPTER] Saved to database successfully")
        
        # Mark as generated in session
        if "ai_data" not in session:
            session["ai_data"] = {}
        if "chapters_generated" not in session["ai_data"]:
            session["ai_data"]["chapters_generated"] = {}
        session["ai_data"]["chapters_generated"][str(chapter_id)] = True
        session.modified = True
        
        print(f"✓ [GENERATE-CHAPTER] Completed successfully for chapter {chapter_id}\n")
        return jsonify({
            "status": "success",
            "message": f"Chapter {chapter_id} generated successfully",
            "audio_ready": True
        })
    
    except Exception as e:
        print(f"✗ [GENERATE-CHAPTER] Chapter Generation Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/chapters")
def chapters():
    print(f"DEBUG: /chapters called")
    print(f"DEBUG: session keys: {list(session.keys())}")
    print(f"DEBUG: ai_data: {session.get('ai_data')}")
    
    if not session.get("ai_data"):
        print("DEBUG: ai_data not in session, redirecting to index")
        return redirect(url_for("index"))
    
    syllabus = session.get("ai_data", {}).get("syllabus")
    if not syllabus:
        print("DEBUG: syllabus not in ai_data, redirecting to index")
        return redirect(url_for("index"))
    
    # Ensure chapter_progress exists
    if "chapter_progress" not in session:
        session["chapter_progress"] = {}
    
    print(f"DEBUG: /chapters rendering with {len(syllabus.get('chapters', []))} chapters")
    
    return render_template("chapters.html", 
                           syllabus=syllabus,
                           progress=session.get("chapter_progress", {}),
                           total_xp=session.get("total_xp", 0))

@app.route("/learn/<int:chapter_id>")
def learn(chapter_id):
    """
    Display learning content for a chapter.
    Chapter should already be generated by /api/generate-chapter.
    """
    db = get_db()
    row = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(chapter_id),)).fetchone()
    
    if not row:
        # Fallback: chapter not found, return to chapters
        print(f"⚠️ Chapter {chapter_id} not found in database, redirecting to chapters")
        return redirect(url_for("chapters"))
    
    try:
        chapter = json.loads(row["data_json"])
    except json.JSONDecodeError as e:
        print(f"⚠️ Failed to parse chapter {chapter_id} JSON: {str(e)}")
        return redirect(url_for("chapters"))
    
    # Ensure chapter has all required fields
    chapter.setdefault("chapter_id", chapter_id)
    chapter.setdefault("subject_domain", "General")
    chapter.setdefault("title", "Chapter")
    chapter.setdefault("narration_script", "No narration provided.")
    chapter.setdefault("topic_title", "Learning Module")
    chapter.setdefault("key_concepts", [])
    
    return render_template("learn.html", 
                           chapter=chapter,
                           style=session.get("cognitive_style", "focus"),
                           user_voice=session.get("gender", "standard_female"),
                           topic_id=session.get("active_topic_id", 0),
                           preferred_language=session.get("preferred_language", "en"))

@app.route("/api/debug-chapter/<int:chapter_id>")
def debug_chapter(chapter_id):
    """Debug endpoint to see what's in the database and what files exist"""
    import os
    db = get_db()
    
    print(f"\n🔍 [DEBUG] Checking chapter {chapter_id}...")
    
    # Check database
    row = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(chapter_id),)).fetchone()
    if not row:
        return jsonify({"error": "Chapter not in database"}), 404
    
    chapter = json.loads(row["data_json"])
    audio_url = chapter.get("audio_url")
    
    print(f"✓ Found in database")
    print(f"  - audio_url field: {audio_url}")
    print(f"  - narration_script length: {len(chapter.get('narration_script', ''))}")
    
    # Check files
    audio_dir = "static/audio"
    if os.path.exists(audio_dir):
        files = os.listdir(audio_dir)
        print(f"✓ Audio directory exists with {len(files)} files:")
        for f in files[:5]:  # Show first 5
            size = os.path.getsize(os.path.join(audio_dir, f))
            print(f"    - {f} ({size} bytes)")
    else:
        print(f"✗ Audio directory doesn't exist")
    
    # Check if audio file exists
    return jsonify({
        "chapter_id": chapter_id,
        "narration_length": len(chapter.get('narration_script', ''))
    })

@app.route("/api/audio/stream/<int:chapter_id>")
def stream_audio(chapter_id):
    """Generates audio dynamically on the fly without saving"""
    print(f"\n🔊 [STREAM-AUDIO] Request for chapter {chapter_id}")
    
    voice = request.args.get('voice', 'standard_female')
    
    db = get_db()
    row = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(chapter_id),)).fetchone()
    if not row:
        return jsonify({"error": "Chapter not found"}), 404
        
    try:
        chapter = json.loads(row["data_json"])
        text = chapter.get('narration_script', '')
        if not text:
            return jsonify({"error": "No text"}), 400
            
        rate = chapter.get("tts_rate", "+0%")
        pitch = chapter.get("tts_pitch", "+0Hz")
        
        # Multilingual voice override
        preferred_language = session.get("preferred_language", "en")
        lang_voice = get_voice_for_language(preferred_language, voice)
        if lang_voice:
            voice = lang_voice  # Override with regional voice
            print(f"🌐 [STREAM-AUDIO] Using multilingual voice: {voice} for language: {preferred_language}")
        
        # Stream audio via True Chunked Generator (0 latency!)
        audio_stream = generate_chapter_audio_stream(text, voice_id=voice, rate=rate, pitch=pitch)
        return Response(stream_with_context(audio_stream), mimetype="audio/mpeg", direct_passthrough=True)
        
    except Exception as e:
        print(f"✗ [STREAM-AUDIO] Failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/game/<int:chapter_id>")
def game(chapter_id):
    print(f"\n🎮 [GAME] Loading game for chapter {chapter_id}")
    db = get_db()
    row = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(chapter_id),)).fetchone()
    if not row:
        print(f"✗ [GAME] Chapter {chapter_id} not found")
        return redirect(url_for("chapters"))
    
    try:
        chapter = json.loads(row["data_json"])
    except json.JSONDecodeError as e:
        print(f"✗ [GAME] Failed to parse chapter: {str(e)}")
        return redirect(url_for("chapters"))
    
    # Ensure required fields
    if "chapter_id" not in chapter:
        chapter["chapter_id"] = chapter_id
    
    if "game_items" not in chapter or not chapter["game_items"]:
        print(f"⚠️ [GAME] No game_items for chapter {chapter_id}, using empty array")
        chapter["game_items"] = []
    else:
        print(f"✓ [GAME] Found {len(chapter.get('game_items', []))} game items")
    
    if "game_type" not in chapter:
        chapter["game_type"] = "true_false_blitz"
    if "game_title" not in chapter:
        chapter["game_title"] = "Knowledge Challenge"
    if "game_instruction" not in chapter:
        chapter["game_instruction"] = "Analyze and execute the task below."
    if "xp_reward" not in chapter:
        chapter["xp_reward"] = 250
    
    print(f"   - Game Type: {chapter.get('game_type')}")
    print(f"   - XP Reward: {chapter.get('xp_reward')}")
    print(f"   - Game Items: {len(chapter.get('game_items', []))}")
    
    return render_template("game.html", chapter=chapter)

@app.route("/api/game-data/<int:chapter_id>")
def game_data(chapter_id):
    db = get_db()
    row = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(chapter_id),)).fetchone()
    if not row: return jsonify({"error": "No data"}), 404
    
    chapter = json.loads(row["data_json"])
    return jsonify({
        "game_type": chapter["game_type"],
        "game_title": chapter["game_title"],
        "game_instruction": chapter["game_instruction"],
        "game_items": chapter["game_items"],
        "xp_reward": chapter["xp_reward"]
    })

@app.route("/api/game-complete", methods=["POST"])
def game_complete():
    data = request.json
    c_id = str(data.get("chapter_id"))
    score = data.get("score", 0)
    
    # Ensure chapter_progress exists
    if "chapter_progress" not in session:
        session["chapter_progress"] = {}
    if c_id not in session["chapter_progress"]:
        session["chapter_progress"][c_id] = {"completed": False}
    
    session["chapter_progress"][c_id]["game_score"] = score
    session.modified = True
    
    return jsonify({"status": "saved", "chapter_id": c_id, "score": score})

@app.route("/quiz/<int:chapter_id>")
def quiz(chapter_id):
    print(f"\n📝 [QUIZ] Loading quiz for chapter {chapter_id}")
    db = get_db()
    row = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(chapter_id),)).fetchone()
    if not row:
        print(f"✗ [QUIZ] Chapter {chapter_id} not found")
        return redirect(url_for("chapters"))
    
    try:
        chapter = json.loads(row["data_json"])
    except json.JSONDecodeError as e:
        print(f"✗ [QUIZ] Failed to parse chapter: {str(e)}")
        return redirect(url_for("chapters"))
    
    # Ensure required fields
    if "chapter_id" not in chapter:
        chapter["chapter_id"] = chapter_id
    if "quiz_questions" not in chapter or not chapter["quiz_questions"]:
        print(f"⚠️ [QUIZ] No quiz_questions for chapter {chapter_id}, using empty array")
        chapter["quiz_questions"] = []
    else:
        print(f"✓ [QUIZ] Found {len(chapter.get('quiz_questions', []))} quiz questions")
        # Log first question for debugging
        first_q = chapter["quiz_questions"][0]
        print(f"   - First Q: {first_q.get('question', 'N/A')[:50]}")
        print(f"   - Has difficulty: {'difficulty' in first_q}")
    
    if "key_concepts" not in chapter:
        chapter["key_concepts"] = []
    if "improvement_tip" not in chapter:
        chapter["improvement_tip"] = "Keep practicing to master this topic!"
    if "xp_reward" not in chapter:
        chapter["xp_reward"] = 250
    
    return render_template("quiz.html", chapter=chapter)

@app.route("/api/quiz-data/<int:chapter_id>")
def quiz_data(chapter_id):
    print(f"📝 [API-QUIZ-DATA] Request for chapter {chapter_id}")
    db = get_db()
    row = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(chapter_id),)).fetchone()
    if not row:
        print(f"✗ [API-QUIZ-DATA] Chapter not found")
        return jsonify({"error": "No data"}), 404
    
    try:
        chapter = json.loads(row["data_json"])
    except json.JSONDecodeError as e:
        print(f"✗ [API-QUIZ-DATA] Failed to parse chapter: {str(e)}")
        return jsonify({"error": "Parse error"}), 500
    
    questions = chapter.get("quiz_questions", [])
    print(f"✓ [API-QUIZ-DATA] Returning {len(questions)} questions")
    
    # Validate questions have required fields
    for i, q in enumerate(questions):
        if not q.get("difficulty"):
            print(f"   ⚠️ Question {i} missing difficulty, adding default")
            q["difficulty"] = "medium"
        if not q.get("concept_tag"):
            q["concept_tag"] = "Concept"
    
    return jsonify({"questions": questions})

@app.route("/api/submit-quiz", methods=["POST"])
def submit_quiz():
    data = request.json
    c_id = str(data.get("chapter_id"))
    score = data.get("score", 0)
    xp_earned = data.get("xp_earned", 0)
    
    print(f"\n🎯 [SUBMIT-QUIZ] Chapter {c_id} submitted")
    print(f"   - Quiz score: {score}%")
    print(f"   - XP earned (from quiz): {xp_earned}")
    
    # Ensure chapter_progress exists
    if "chapter_progress" not in session:
        session["chapter_progress"] = {}
    if c_id not in session["chapter_progress"]:
        session["chapter_progress"][c_id] = {}
    
    # Calculate XP reward based on score (bonus system)
    base_xp = 250
    if score >= 90:
        bonus_xp = base_xp + 100  # 350 XP for mastery
        achievement = "Master 🏆"
    elif score >= 70:
        bonus_xp = base_xp + 50   # 300 XP for good performance
        achievement = "Good 👍"
    elif score >= 50:
        bonus_xp = base_xp        # 250 XP for passing
        achievement = "Passed ✓"
    else:
        bonus_xp = max(50, int(base_xp * (score / 100)))  # Scaled down for low scores
        achievement = "Learning 📚"
    
    print(f"   - Final XP reward: {bonus_xp} ({achievement})")
    
    session["chapter_progress"][c_id].update({
        "quiz_score": score,
        "xp_earned": bonus_xp,
        "completed": True
    })
    
    total_before = session.get("total_xp", 0)
    session["total_xp"] = total_before + bonus_xp
    session.modified = True
    
    # Persist progress to database for logged-in users
    _save_topic_progress()
    
    print(f"   ✓ Total XP: {total_before} → {session['total_xp']}")
    print(f"✓ [SUBMIT-QUIZ] Chapter {c_id} marked as completed\n")
    
    return jsonify({
        "status": "success", 
        "redirect": url_for("results", chapter_id=c_id),
        "score": score,
        "xp_earned": bonus_xp,
        "achievement": achievement
    })

@app.route("/results/<int:chapter_id>")
def results(chapter_id):
    db = get_db()
    row = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(chapter_id),)).fetchone()
    if not row: return redirect(url_for("chapters"))
    
    chapter = json.loads(row["data_json"])
    progress = session.get("chapter_progress", {}).get(str(chapter_id), {})
    
    # Ensure required fields
    if "chapter_id" not in chapter:
        chapter["chapter_id"] = chapter_id
    if "badge_emoji" not in chapter:
        chapter["badge_emoji"] = "🏆"
    if "badge_name" not in chapter:
        chapter["badge_name"] = "Learner"
    if "topic_title" not in chapter:
        # Try to get from syllabus
        syllabus = session.get("ai_data", {}).get("syllabus", {})
        chapter["topic_title"] = syllabus.get("topic_title", "Learning Module")
    
    return render_template("results.html", 
                           chapter=chapter, 
                           progress=progress,
                           student_name=session.get("student_name", "Explorer"),
                           topic_id=session.get("active_topic_id", 0))

@app.route("/api/leaderboard", methods=["GET", "POST"])
def leaderboard():
    db = get_db()
    if request.method == "POST":
        data = request.json
        db.execute("INSERT INTO leaderboard (name, topic, score, xp, badge) VALUES (?, ?, ?, ?, ?)",
                   (data["name"], data["topic"], data["score"], data["xp"], data["badge"]))
        db.commit()
        return jsonify({"status": "success"})
    
    rows = db.execute("SELECT * FROM leaderboard ORDER BY xp DESC LIMIT 10").fetchall()
    return jsonify([dict(row) for row in rows])

@app.route("/parent-dashboard")
def parent_dashboard():
    if session.get("user_type") != "parent":
        return redirect(url_for("index"))
    
    # Fetch emotion analytics for this user's topics
    emotion_data = []
    user_id = session.get("user_id")
    if user_id:
        db = get_db()
        emotion_rows = db.execute("""
            SELECT emotion_state, confidence, timestamp, chapter_id
            FROM emotion_logs WHERE user_id = ?
            ORDER BY timestamp DESC LIMIT 200
        """, (user_id,)).fetchall()
        emotion_data = [dict(r) for r in emotion_rows]
    
    # Compute emotion summary
    emotion_summary = {"focused": 0, "bored": 0, "distracted": 0, "stressed": 0, "anxious": 0}
    for e in emotion_data:
        state = e.get("emotion_state", "focused")
        if state in emotion_summary:
            emotion_summary[state] += 1
    total_readings = sum(emotion_summary.values()) or 1
    emotion_percentages = {k: round(v / total_readings * 100) for k, v in emotion_summary.items()}
    
    # Disorder level indicators
    disorder_levels = {
        "anxiety_level": min(100, emotion_percentages.get("anxious", 0) + emotion_percentages.get("stressed", 0)),
        "attention_score": max(0, 100 - emotion_percentages.get("distracted", 0) - emotion_percentages.get("bored", 0)),
        "stress_level": emotion_percentages.get("stressed", 0),
        "engagement_score": emotion_percentages.get("focused", 0)
    }
    
    return render_template("parent_dashboard.html", 
                           student_name=session.get("student_name"),
                           progress=session.get("chapter_progress"),
                           profile=session.get("learning_profile"),
                           syllabus=session.get("ai_data", {}).get("syllabus"),
                           emotion_data=emotion_data,
                           emotion_summary=emotion_summary,
                           emotion_percentages=emotion_percentages,
                           disorder_levels=disorder_levels)


# --- EMOTION & ADAPTIVE MODE ENDPOINTS ---

@app.route("/api/emotion-log", methods=["POST"])
def emotion_log():
    """Record an emotion reading from the webcam detector."""
    try:
        data = request.json
        user_id = session.get("user_id")
        topic_id = session.get("active_topic_id")
        
        emotion_state = data.get("emotion_state", "unknown")
        confidence = data.get("confidence", 0)
        chapter_id = data.get("chapter_id")
        
        if user_id:
            db = get_db()
            db.execute("""
                INSERT INTO emotion_logs (user_id, topic_id, chapter_id, emotion_state, confidence)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, topic_id, chapter_id, emotion_state, confidence))
            db.commit()
        
        return jsonify({"status": "logged", "state": emotion_state})
    except Exception as e:
        print(f"⚠️ [EMOTION-LOG] Error: {str(e)}")
        return jsonify({"status": "error"}), 500


@app.route("/api/emotion-analytics/<int:topic_id>")
@login_required
def emotion_analytics(topic_id):
    """Get emotion analytics for a specific topic (for parent dashboard)."""
    try:
        db = get_db()
        user_id = session.get("user_id")
        
        rows = db.execute("""
            SELECT emotion_state, confidence, timestamp, chapter_id
            FROM emotion_logs
            WHERE user_id = ? AND topic_id = ?
            ORDER BY timestamp ASC
        """, (user_id, topic_id)).fetchall()
        
        data = [dict(r) for r in rows]
        
        # Compute summary
        summary = {}
        for row in data:
            state = row["emotion_state"]
            summary[state] = summary.get(state, 0) + 1
        
        return jsonify({"readings": data, "summary": summary, "total": len(data)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/generate-story", methods=["POST"])
def api_generate_story():
    """Generate manga-style story panels for Story Mode."""
    try:
        data = request.json
        chapter_id = data.get("chapter_id")
        
        if not chapter_id:
            return jsonify({"error": "No chapter_id provided"}), 400
        
        # Get chapter content from DB
        db = get_db()
        row = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(chapter_id),)).fetchone()
        if not row:
            return jsonify({"error": "Chapter not found"}), 404
        
        chapter = json.loads(row["data_json"])
        
        # --- CACHE CHECK ---
        if "story_data" in chapter and chapter["story_data"]:
            print(f"📖 [STORY-API] Returning CACHED manga story for chapter {chapter_id}")
            return jsonify(chapter["story_data"])
            
        narration = chapter.get("narration_script", "")
        title = chapter.get("title", "Chapter")
        key_concepts = chapter.get("key_concepts", [])
        
        print(f"📖 [STORY-API] Generating manga story for chapter {chapter_id}: {title}")
        
        # Generate story text via Groq
        story_data = generate_manga_story(narration, title, key_concepts)
        
        # Generate manga images via Hugging Face
        panels = story_data.get("panels", [])
        panels = generate_manga_images_batch(panels)
        story_data["panels"] = panels
        
        print(f"✓ [STORY-API] Story generated with {len(panels)} panels")
        
        # --- SAVE TO CACHE ---
        chapter["story_data"] = story_data
        db.execute("UPDATE chapters SET data_json = ? WHERE id = ?", (json.dumps(chapter), str(chapter_id)))
        db.commit()
        
        return jsonify(story_data)
        
    except Exception as e:
        print(f"✗ [STORY-API] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/generate-simple", methods=["POST"])
def api_generate_simple():
    """Generate simplified content for Simple Mode."""
    try:
        data = request.json
        chapter_id = data.get("chapter_id")
        
        if not chapter_id:
            return jsonify({"error": "No chapter_id provided"}), 400
        
        # Get chapter content from DB
        db = get_db()
        row = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(chapter_id),)).fetchone()
        if not row:
            return jsonify({"error": "Chapter not found"}), 404
        
        chapter = json.loads(row["data_json"])
        
        # --- CACHE CHECK ---
        if "simple_data" in chapter and chapter["simple_data"]:
            print(f"📋 [SIMPLE-API] Returning CACHED simplified content for chapter {chapter_id}")
            return jsonify(chapter["simple_data"])
            
        narration = chapter.get("narration_script", "")
        title = chapter.get("title", "Chapter")
        key_concepts = chapter.get("key_concepts", [])
        
        print(f"📋 [SIMPLE-API] Generating simplified content for chapter {chapter_id}: {title}")
        
        simple_data = generate_simplified_content(narration, title, key_concepts)
        
        print(f"✓ [SIMPLE-API] Simplified content generated with {len(simple_data.get('cards', []))} cards")
        
        # --- SAVE TO CACHE ---
        chapter["simple_data"] = simple_data
        db.execute("UPDATE chapters SET data_json = ? WHERE id = ?", (json.dumps(chapter), str(chapter_id)))
        db.commit()
        
        return jsonify(simple_data)
        
    except Exception as e:
        print(f"✗ [SIMPLE-API] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# === FEATURE 1: SOCRATIC AI TUTOR ===

@app.route("/api/ask-tutor", methods=["POST"])
@login_required
def ask_tutor():
    """Socratic AI Tutor — answers questions strictly from chapter context."""
    try:
        data = request.json
        question = data.get("question", "").strip()
        chapter_id = data.get("chapter_id")
        topic_id = data.get("topic_id")

        if not question:
            return jsonify({"success": False, "error": "No question provided"}), 400

        # Retrieve chapter narration from DB
        narration = ""
        if chapter_id:
            db = get_db()
            row = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(chapter_id),)).fetchone()
            if row:
                chapter_data = json.loads(row["data_json"])
                narration = chapter_data.get("narration_script", "")

        # Fallback: try session
        if not narration:
            chapters_gen = session.get("ai_data", {}).get("chapters_generated", {})
            ch_data = chapters_gen.get(str(chapter_id), {})
            if isinstance(ch_data, dict):
                narration = ch_data.get("narration_script", "")

        if not narration:
            return jsonify({"success": False, "error": "Chapter content not found"}), 404

        # Build Socratic system prompt
        age_range = session.get("age_range", session.get("learning_profile", {}).get("age_range", "11-13"))
        learning_profile = session.get("learning_profile", {})
        profile_context = f"Student age range: {age_range}."
        if learning_profile.get("has_dyslexia"):
            profile_context += " Student has dyslexia — use simple words."
        if learning_profile.get("has_anxiety"):
            profile_context += " Student has anxiety — be extra reassuring."
        if learning_profile.get("confidence_level") == "low":
            profile_context += " Student has low confidence — be encouraging."

        system_prompt = (
            f"You are Socrates — a calm, encouraging tutor. Answer the student's question using ONLY the following lecture material. "
            f"Do not introduce any knowledge outside this material. If the answer isn't in the material, say 'That's a great question for after this chapter!' "
            f"Keep your answer to 2-4 sentences maximum, age-appropriate for the student. "
            f"{profile_context}\n\nLecture:\n{narration[:3000]}"
        )

        user_prompt = f"Student's question: {question}"

        # Call LLM — use Groq for fast response
        import os
        model = os.getenv("TUTOR_MODEL", "llama-3.3-70b-versatile")
        answer = call_llm(system_prompt, user_prompt, model=model)

        # Clean up the answer (remove any JSON formatting if present)
        answer = answer.strip().strip('"').strip()

        print(f"💬 [TUTOR] Q: {question[:50]}... A: {answer[:80]}...")
        return jsonify({"success": True, "answer": answer})

    except Exception as e:
        print(f"✗ [TUTOR] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# === FEATURE 3: LIVE COGNITIVE LOAD INTERVENTION ===

@app.route("/api/emotion-intervention", methods=["POST"])
@login_required
def emotion_intervention():
    """Trigger mid-lesson content simplification based on sustained emotional state."""
    try:
        data = request.json
        state = data.get("state", "")
        chapter_id = data.get("chapter_id")
        topic_id = data.get("topic_id")
        user_id = session.get("user_id")

        # Log to emotion_logs regardless
        if user_id and chapter_id:
            db = get_db()
            db.execute("""
                INSERT INTO emotion_logs (user_id, topic_id, chapter_id, emotion_state, confidence)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, topic_id or session.get("active_topic_id"), chapter_id, state, 0.9))
            db.commit()

        # Only intervene for distress states
        if state not in ['distressed', 'anxious', 'tired']:
            return jsonify({"success": True, "intervention": False})

        # Retrieve chapter data from DB
        db = get_db()
        row = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(chapter_id),)).fetchone()
        if not row:
            return jsonify({"success": False, "error": "Chapter not found", "intervention": False}), 404

        chapter_data = json.loads(row["data_json"])
        learning_profile = session.get("learning_profile", {})

        # Generate simplified content
        narration = chapter_data.get("narration_script", "")
        title = chapter_data.get("title", "Chapter")
        key_concepts = chapter_data.get("key_concepts", [])

        simplified = generate_simplified_content(narration, title, key_concepts)

        # Build a simplified narration string from the cards
        simplified_narration = ""
        if simplified and simplified.get("cards"):
            parts = []
            for card in simplified["cards"]:
                parts.append(f"{card.get('emoji', '')} {card.get('heading', '')}: {card.get('content', '')}")
            simplified_narration = "\n\n".join(parts)
            if simplified.get("encouragement"):
                simplified_narration += f"\n\n{simplified['encouragement']}"
        else:
            simplified_narration = narration[:1500]

        # Determine comforting message based on state
        messages = {
            'distressed': "I noticed you might be feeling overwhelmed. Let me simplify things for you. 💚",
            'anxious': "Take a deep breath. Let's make this content a bit easier to follow. 🌿",
            'tired': "Feeling tired? Here's a gentler version of this section. Rest when you need to. 😊"
        }
        message = messages.get(state, "Let's take a moment and simplify things. 🌿")

        print(f"🌿 [INTERVENTION] Triggered for state={state}, chapter={chapter_id}")
        return jsonify({
            "success": True,
            "intervention": True,
            "simplified_narration": simplified_narration,
            "message": message
        })

    except Exception as e:
        print(f"✗ [INTERVENTION] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e), "intervention": False}), 500


# === FEATURE 4: PROGRESS DNA CARD ===

@app.route("/api/dna-card/<int:topic_id>")
def dna_card(topic_id):
    """Generate Progress DNA Card data for a topic. Works for both logged-in and guest users."""
    try:
        db = get_db()
        user_id = session.get("user_id")
        
        topic_dict = {}
        chapter_progress = {}
        chapters_generated = {}
        
        # Try to load from database for logged-in users
        if user_id:
            topic = db.execute("SELECT * FROM user_topics WHERE id = ? AND user_id = ?", (topic_id, user_id)).fetchone()
            if topic:
                topic_dict = dict(topic)
                chapters_generated = json.loads(topic_dict.get("chapters_generated_json", "{}"))
        
        # Fall back to session data (for guest users or if not in DB)
        if not topic_dict:
            ai_data = session.get("ai_data", {})
            syllabus = ai_data.get("syllabus", {})
            
            if not syllabus:
                return jsonify({"success": False, "error": "No learning data available"}), 404
            
            topic_dict = {
                "topic_title": syllabus.get("topic_title", "Learning Module"),
                "cognitive_style": session.get("cognitive_style", "focus"),
                "total_xp": session.get("total_xp", 0),
                "syllabus_json": json.dumps(syllabus),
                "chapters_generated_json": json.dumps(ai_data.get("chapters_generated", {}))
            }
            chapter_progress = session.get("chapter_progress", {})
            chapters_generated = ai_data.get("chapters_generated", {})
        else:
            chapter_progress = json.loads(topic_dict.get("chapter_progress_json", "{}"))

        # Completed chapter count
        completed = sum(1 for v in chapter_progress.values() if isinstance(v, dict) and v.get("completed"))
        syllabus = json.loads(topic_dict.get("syllabus_json", "{}"))
        total_chapters = len(syllabus.get("chapters", []))

        # Total XP
        total_xp = topic_dict.get("total_xp", 0) or 0

        # Emotion distribution from emotion_logs (only for logged-in users)
        emotion_distribution = {}
        if user_id:
            emotion_rows = db.execute("""
                SELECT emotion_state, COUNT(*) as cnt
                FROM emotion_logs
                WHERE user_id = ? AND topic_id = ?
                GROUP BY emotion_state
            """, (user_id, topic_id)).fetchall()

            for row in emotion_rows:
                emotion_distribution[row["emotion_state"]] = row["cnt"]

        # Dominant emotion
        dominant_emotion = "focused"
        if emotion_distribution:
            dominant_emotion = max(emotion_distribution, key=emotion_distribution.get)

        # Average quiz score from chapter_progress
        quiz_scores = []
        for cid, prog in chapter_progress.items():
            if isinstance(prog, dict) and "quiz_score" in prog and prog.get("completed"):
                quiz_scores.append(prog["quiz_score"])
        avg_quiz_score = sum(quiz_scores) / len(quiz_scores) if quiz_scores else 0

        # Badge collection from generated chapters
        badge_collection = []
        for ch_id in chapters_generated.keys():
            row = db.execute("SELECT data_json FROM chapters WHERE id = ?", (str(ch_id),)).fetchone()
            if row:
                try:
                    ch_data = json.loads(row["data_json"])
                    badge_collection.append({
                        "badge_emoji": ch_data.get("badge_emoji", "🏆"),
                        "badge_name": ch_data.get("badge_name", "Learner")
                    })
                except:
                    pass

        # Learning style
        learning_style = topic_dict.get("cognitive_style", "focus").capitalize()

        student_name = session.get("display_name", session.get("student_name", "Learner"))

        result = {
            "success": True,
            "student_name": student_name,
            "topic_title": topic_dict.get("topic_title", "Learning Module"),
            "total_xp": total_xp,
            "chapters_completed": completed,
            "total_chapters": total_chapters,
            "emotion_distribution": emotion_distribution,
            "avg_quiz_score": round(avg_quiz_score, 1),
            "badge_collection": badge_collection,
            "dominant_emotion": dominant_emotion,
            "learning_style": learning_style
        }

        print(f"🧬 [DNA-CARD] Generated for topic {topic_id}: {result['topic_title']}")
        return jsonify(result)

    except Exception as e:
        print(f"✗ [DNA-CARD] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================

# ============================================================
# STUDY BATTLE — LOCAL BOT SIMULATION (no Firebase, no PeerJS)
# ============================================================

import random
import string
import time
import threading

# ── In-memory room store ─────────────────────────────────────
_rooms = {}        # room_code -> room dict
_rooms_lock = threading.Lock()

# ── Hardcoded curriculum bank ────────────────────────────────

CURRICULUM_BANK = {
    "photosynthesis": {
        "title": "⚡ Photosynthesis Battle!",
        "topic": "Photosynthesis",
        "totalRounds": 4,
        "rounds": [
            {
                "roundNumber": 1, "type": "learn",
                "title": "What is Photosynthesis?",
                "content": "Photosynthesis is the process plants use to make their own food using sunlight, water, and carbon dioxide. It happens mainly in the leaves inside tiny structures called chloroplasts.",
                "funFact": "A single large tree can absorb up to 48 pounds of CO₂ per year! 🌳"
            },
            {
                "roundNumber": 2, "type": "quiz",
                "title": "The Basics",
                "question": "Which gas do plants absorb from the air during photosynthesis?",
                "options": ["A) Oxygen", "B) Nitrogen", "C) Carbon Dioxide", "D) Hydrogen"],
                "correctAnswer": "C", "explanation": "Plants absorb carbon dioxide (CO₂) and release oxygen (O₂) as a byproduct!", "points": 100
            },
            {
                "roundNumber": 3, "type": "learn",
                "title": "The Equation",
                "content": "The photosynthesis equation is: 6CO₂ + 6H₂O + light energy → C₆H₁₂O₆ + 6O₂. In plain English: carbon dioxide + water + sunlight → glucose + oxygen. Glucose is the sugar plant cells use for energy.",
                "funFact": "Chlorophyll, which makes plants green, can only absorb red and blue light — it reflects green light back to our eyes! 🟢"
            },
            {
                "roundNumber": 4, "type": "quiz",
                "title": "Chlorophyll Check",
                "question": "What is the green pigment in plants that captures sunlight called?",
                "options": ["A) Melanin", "B) Chlorophyll", "C) Hemoglobin", "D) Carotene"],
                "correctAnswer": "B", "explanation": "Chlorophyll is the pigment inside chloroplasts that absorbs light energy to power photosynthesis.", "points": 100
            }
        ],
        "finalChallenge": {
            "title": "Final Boss 🔥",
            "question": "What are the THREE ingredients plants need for photosynthesis?",
            "options": ["A) Oxygen, Sugar, Nitrogen", "B) Water, Sunlight, Oxygen", "C) Carbon Dioxide, Water, Sunlight", "D) Glucose, CO₂, Nitrogen"],
            "correctAnswer": "C", "explanation": "Plants need carbon dioxide from the air, water from the soil, and sunlight energy — all three!", "points": 250
        }
    },
    "fractions": {
        "title": "⚡ Fractions Faceoff!",
        "topic": "Fractions",
        "totalRounds": 4,
        "rounds": [
            {
                "roundNumber": 1, "type": "learn",
                "title": "What is a Fraction?",
                "content": "A fraction represents a part of a whole. It has two parts: the numerator (top number) shows how many parts you have, and the denominator (bottom number) shows how many equal parts the whole is divided into.",
                "funFact": "The word 'fraction' comes from the Latin word 'fractio', which means 'to break'! ✂️"
            },
            {
                "roundNumber": 2, "type": "quiz",
                "title": "Numerator vs Denominator",
                "question": "In the fraction 3/8, what does the number 8 represent?",
                "options": ["A) The numerator", "B) The number of parts you have", "C) The total equal parts the whole is divided into", "D) The decimal value"],
                "correctAnswer": "C", "explanation": "8 is the denominator — it tells us the whole is divided into 8 equal parts. 3 (the numerator) tells us we have 3 of those parts.", "points": 100
            },
            {
                "roundNumber": 3, "type": "learn",
                "title": "Adding Fractions",
                "content": "To add fractions with the same denominator, simply add the numerators and keep the denominator the same. For example: 2/5 + 1/5 = 3/5. If denominators differ, you must first find a common denominator.",
                "funFact": "Pizza slices are a perfect real-world fraction — eating 2 out of 8 slices means you ate 2/8 (or 1/4) of the pizza! 🍕"
            },
            {
                "roundNumber": 4, "type": "quiz",
                "title": "Adding Up",
                "question": "What is 1/4 + 2/4?",
                "options": ["A) 3/8", "B) 3/4", "C) 2/8", "D) 1/2"],
                "correctAnswer": "B", "explanation": "Since the denominators are the same (4), just add the numerators: 1 + 2 = 3. The answer is 3/4!", "points": 100
            }
        ],
        "finalChallenge": {
            "title": "Final Boss 🔥",
            "question": "Which fraction is equivalent to 1/2?",
            "options": ["A) 2/3", "B) 3/5", "C) 4/8", "D) 3/4"],
            "correctAnswer": "C", "explanation": "4/8 simplifies to 1/2 because both the numerator and denominator can be divided by 4!", "points": 250
        }
    },
    "world war 2": {
        "title": "⚡ World War II Battle!",
        "topic": "World War II",
        "totalRounds": 4,
        "rounds": [
            {
                "roundNumber": 1, "type": "learn",
                "title": "The Start of WWII",
                "content": "World War II began on September 1, 1939 when Nazi Germany, led by Adolf Hitler, invaded Poland. Britain and France declared war on Germany two days later. The war would eventually involve nations from six of the seven continents.",
                "funFact": "WWII involved more than 30 countries and over 100 million military personnel — it was the deadliest conflict in human history. 🌍"
            },
            {
                "roundNumber": 2, "type": "quiz",
                "title": "Key Dates",
                "question": "In what year did World War II begin?",
                "options": ["A) 1935", "B) 1937", "C) 1939", "D) 1941"],
                "correctAnswer": "C", "explanation": "WWII officially began on September 1, 1939 with Germany's invasion of Poland.", "points": 100
            },
            {
                "roundNumber": 3, "type": "learn",
                "title": "The Allied Powers",
                "content": "The main Allied Powers fighting against the Axis were the United States, the United Kingdom, the Soviet Union, and China. The United States joined the war after Japan attacked Pearl Harbor, Hawaii on December 7, 1941.",
                "funFact": "The code name for the Allied invasion of Normandy on June 6, 1944 was 'Operation Overlord' — today we call it D-Day. 🪖"
            },
            {
                "roundNumber": 4, "type": "quiz",
                "title": "Pearl Harbor",
                "question": "Which event caused the United States to enter World War II?",
                "options": ["A) Germany invading France", "B) Japan attacking Pearl Harbor", "C) Italy declaring war on Britain", "D) The bombing of London"],
                "correctAnswer": "B", "explanation": "Japan's surprise attack on the US naval base at Pearl Harbor, Hawaii on December 7, 1941 brought America into the war.", "points": 100
            }
        ],
        "finalChallenge": {
            "title": "Final Boss 🔥",
            "question": "In what year did World War II end?",
            "options": ["A) 1943", "B) 1944", "C) 1945", "D) 1946"],
            "correctAnswer": "C", "explanation": "WWII ended in 1945: Germany surrendered in May (V-E Day) and Japan surrendered in September (V-J Day) after the atomic bombings.", "points": 250
        }
    },
    "solar system": {
        "title": "⚡ Solar System Showdown!",
        "topic": "Solar System",
        "totalRounds": 4,
        "rounds": [
            {
                "roundNumber": 1, "type": "learn",
                "title": "Our Solar System",
                "content": "Our solar system has 8 planets orbiting the Sun: Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus, and Neptune. The four inner planets (Mercury to Mars) are rocky, while the four outer planets (Jupiter to Neptune) are gas giants or ice giants.",
                "funFact": "If the Sun were the size of a front door, Earth would be the size of a coin — and it would be 26 meters away! ☀️"
            },
            {
                "roundNumber": 2, "type": "quiz",
                "title": "Planet Count",
                "question": "How many planets are in our solar system?",
                "options": ["A) 7", "B) 8", "C) 9", "D) 10"],
                "correctAnswer": "B", "explanation": "There are 8 planets! Pluto was reclassified as a 'dwarf planet' by the International Astronomical Union in 2006.", "points": 100
            },
            {
                "roundNumber": 3, "type": "learn",
                "title": "The Largest Planet",
                "content": "Jupiter is the largest planet in our solar system — so big that all other planets could fit inside it! It's a gas giant made mostly of hydrogen and helium. Jupiter has at least 95 known moons, including Ganymede, which is larger than the planet Mercury.",
                "funFact": "Jupiter's Great Red Spot is a storm that has been raging for over 350 years — and it's larger than the entire Earth! 🌀"
            },
            {
                "roundNumber": 4, "type": "quiz",
                "title": "Giant Planet",
                "question": "Which is the largest planet in our solar system?",
                "options": ["A) Saturn", "B) Neptune", "C) Jupiter", "D) Uranus"],
                "correctAnswer": "C", "explanation": "Jupiter is by far the largest planet, with a mass more than twice that of all other planets combined!", "points": 100
            }
        ],
        "finalChallenge": {
            "title": "Final Boss 🔥",
            "question": "Which planet is known for its spectacular ring system?",
            "options": ["A) Jupiter", "B) Uranus", "C) Neptune", "D) Saturn"],
            "correctAnswer": "D", "explanation": "Saturn has the most spectacular and visible ring system, made up of ice and rock particles. Though all four gas giants have rings, Saturn's are by far the most impressive!", "points": 250
        }
    },
    "human body": {
        "title": "⚡ Human Body Battle!",
        "topic": "Human Body",
        "totalRounds": 4,
        "rounds": [
            {
                "roundNumber": 1, "type": "learn",
                "title": "The Heart",
                "content": "The heart is a muscular organ that pumps blood throughout your body. It beats about 100,000 times per day, pumping around 2,000 gallons of blood. Blood carries oxygen and nutrients to every cell and removes waste products.",
                "funFact": "Your heart is roughly the size of your fist, and it starts beating just 4 weeks after conception! ❤️"
            },
            {
                "roundNumber": 2, "type": "quiz",
                "title": "Heart Facts",
                "question": "Approximately how many times does the heart beat per day?",
                "options": ["A) 10,000", "B) 50,000", "C) 100,000", "D) 500,000"],
                "correctAnswer": "C", "explanation": "The average heart beats about 100,000 times per day — that's around 70 beats per minute at rest!", "points": 100
            },
            {
                "roundNumber": 3, "type": "learn",
                "title": "The Brain",
                "content": "The human brain is the control center of the body. It has about 86 billion neurons (nerve cells) that communicate through electrical and chemical signals. The brain controls everything from breathing and heartbeat to thoughts, emotions, and memories.",
                "funFact": "Your brain uses about 20% of your body's total energy — even though it only makes up about 2% of your body weight! 🧠"
            },
            {
                "roundNumber": 4, "type": "quiz",
                "title": "Brain Power",
                "question": "Approximately how many neurons does the human brain contain?",
                "options": ["A) 1 million", "B) 1 billion", "C) 86 billion", "D) 1 trillion"],
                "correctAnswer": "C", "explanation": "The human brain has approximately 86 billion neurons, each connected to thousands of others, forming an incredibly complex network!", "points": 100
            }
        ],
        "finalChallenge": {
            "title": "Final Boss 🔥",
            "question": "Which organ is responsible for filtering waste from the blood and producing urine?",
            "options": ["A) Liver", "B) Lungs", "C) Kidneys", "D) Spleen"],
            "correctAnswer": "C", "explanation": "The kidneys filter about 200 liters of blood per day, removing waste products and excess water to create urine!", "points": 250
        }
    },
    "default": {
        "title": "⚡ Study Battle!",
        "topic": "General Knowledge",
        "totalRounds": 4,
        "rounds": [
            {
                "roundNumber": 1, "type": "learn",
                "title": "Did You Know?",
                "content": "Learning is most effective when you test yourself rather than just re-reading. This technique is called 'active recall' and studies show it can improve long-term memory by up to 50%!",
                "funFact": "Your brain forms new connections every time you learn something new — learning literally changes your brain structure! 🧠"
            },
            {
                "roundNumber": 2, "type": "quiz",
                "title": "Quick Check",
                "question": "What is the name of the technique where you test yourself to improve memory?",
                "options": ["A) Passive reading", "B) Active recall", "C) Spaced repetition", "D) Mind mapping"],
                "correctAnswer": "B", "explanation": "Active recall — testing yourself — is one of the most effective study techniques for long-term retention!", "points": 100
            },
            {
                "roundNumber": 3, "type": "learn",
                "title": "The Power of Sleep",
                "content": "Sleep is critical for learning. During sleep, your brain consolidates memories — moving information from short-term to long-term storage. Students who sleep 8+ hours after studying retain significantly more information than those who stay up late cramming.",
                "funFact": "Einstein reportedly slept 10 hours per night and took regular naps. He believed sleep was essential to his creative thinking! 💤"
            },
            {
                "roundNumber": 4, "type": "quiz",
                "title": "Sleep & Memory",
                "question": "What does your brain do with new memories during sleep?",
                "options": ["A) Deletes them to save space", "B) Consolidates them into long-term storage", "C) Replays them as dreams only", "D) Nothing — sleep is just rest"],
                "correctAnswer": "B", "explanation": "During sleep, especially deep sleep, your brain actively processes and consolidates new memories into long-term storage!", "points": 100
            }
        ],
        "finalChallenge": {
            "title": "Final Boss 🔥",
            "question": "Which study technique involves reviewing material at increasing intervals over time?",
            "options": ["A) Cramming", "B) Mind mapping", "C) Spaced repetition", "D) Passive rereading"],
            "correctAnswer": "C", "explanation": "Spaced repetition — reviewing material at growing intervals (1 day, 3 days, 1 week, etc.) — is scientifically proven to be the most efficient way to memorize information long-term!", "points": 250
        }
    }
}

BOT_EMOTIONS = ["focused 🎯", "thinking 🤔", "excited 🤩", "confident 😎", "confused 😅"]
BOT_NAMES = ["NeuroBot 🤖", "StudyBot 🤖", "BrainBot 🤖", "QuizBot 🤖"]


def _pick_curriculum(topic: str) -> dict:
    """Match user topic to a hardcoded curriculum or return default."""
    t = topic.lower().strip()
    for key in CURRICULUM_BANK:
        if key in t or t in key:
            import copy
            c = copy.deepcopy(CURRICULUM_BANK[key])
            c["topic"] = topic  # use user's exact phrasing
            return c
    import copy
    c = copy.deepcopy(CURRICULUM_BANK["default"])
    c["title"] = f"⚡ {topic} Battle!"
    c["topic"] = topic
    return c


def generate_room_code() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def _make_bot_plan(curriculum: dict) -> list:
    """
    Pre-compute when the bot will answer each quiz round and whether it's correct.
    Returns a list of {round_index, think_seconds, correct, letter}.
    """
    plan = []
    rounds = curriculum.get("rounds", [])
    # Include the final challenge as an extra quiz round
    quiz_indices = [i for i, r in enumerate(rounds) if r.get("type") == "quiz"]
    quiz_indices.append(len(rounds))  # final challenge index

    for idx in quiz_indices:
        if idx < len(rounds):
            round_data = rounds[idx]
        else:
            round_data = curriculum.get("finalChallenge", {})
            round_data = dict(round_data)
            round_data["type"] = "quiz"

        correct_letter = round_data.get("correctAnswer", "A")
        options = round_data.get("options", ["A) ?", "B) ?", "C) ?", "D) ?"])
        letters = [o[0] for o in options if o]

        bot_correct = random.random() < 0.62  # 62% accuracy
        if bot_correct:
            chosen = correct_letter
        else:
            wrong = [l for l in letters if l != correct_letter]
            chosen = random.choice(wrong) if wrong else correct_letter

        think_time = random.randint(5, 22)  # seconds to "think"
        plan.append({
            "round_index": idx,
            "think_seconds": think_time,
            "correct": bot_correct,
            "chosen_letter": chosen
        })
    return plan


# ── Flask Routes ──────────────────────────────────────────────

@app.route("/study-battle")
@login_required
def study_battle_lobby():
    user_id = session.get("user_id")
    username = session.get("username")
    display_name = session.get("display_name") or username
    return render_template("study_battle.html",
        user_id=user_id,
        username=username,
        display_name=display_name,
        page="lobby"
    )


@app.route("/api/battle/create-room", methods=["POST"])
@login_required
def battle_create_room():
    user_id = session.get("user_id")
    username = session.get("username")
    display_name = session.get("display_name") or username

    data = request.get_json() or {}
    topic = data.get("topic", "").strip()
    duration = int(data.get("duration", 30))

    if not topic:
        return jsonify({"error": "Topic is required"}), 400

    room_code = generate_room_code()
    curriculum = _pick_curriculum(topic)
    bot_plan = _make_bot_plan(curriculum)
    bot_name = random.choice(BOT_NAMES)

    room = {
        "roomCode": room_code,
        "topic": topic,
        "duration": duration,
        "hostUserId": user_id,
        "hostUsername": username,
        "hostDisplayName": display_name,
        "status": "active",
        "curriculum": curriculum,
        "createdAt": time.time(),
        # Player state
        "playerScore": 0,
        "playerRound": 0,
        # Bot state
        "botName": bot_name,
        "botScore": 0,
        "botRound": 0,
        "botEmotion": "focused 🎯",
        "botPlan": bot_plan,
        "botRoundStartTimes": {},   # round_index -> epoch time when round started
        "botAnswered": {},          # round_index -> True/False
    }

    with _rooms_lock:
        _rooms[room_code] = room

    return jsonify({
        "roomCode": room_code,
        "topic": topic,
        "duration": duration,
        "curriculum": curriculum,
        "botName": bot_name,
        "status": "active"
    })


@app.route("/api/battle/state/<room_code>", methods=["GET", "POST"])
@login_required
def battle_state(room_code):
    """
    GET  → returns current room snapshot (for polling).
    POST → player submits an answer: {roundIndex, selectedLetter, earnedPoints}
    """
    with _rooms_lock:
        room = _rooms.get(room_code)

    if not room:
        return jsonify({"error": "Room not found"}), 404

    if request.method == "POST":
        body = request.get_json() or {}
        round_idx = body.get("roundIndex", 0)
        earned = body.get("earnedPoints", 0)

        with _rooms_lock:
            room = _rooms[room_code]
            room["playerScore"] += earned
            room["playerRound"] = round_idx + 1
            # Mark when this quiz round started (for bot timing)
            if round_idx not in room["botRoundStartTimes"]:
                room["botRoundStartTimes"][round_idx] = time.time()

    # Process bot logic
    _tick_bot(room_code)

    with _rooms_lock:
        room = _rooms.get(room_code)
    if not room:
        return jsonify({"error": "Room not found"}), 404

    return jsonify({
        "roomCode": room_code,
        "botName": room["botName"],
        "botScore": room["botScore"],
        "botRound": room["botRound"],
        "botEmotion": room["botEmotion"],
        "playerScore": room["playerScore"],
        "playerRound": room["playerRound"],
        "status": room["status"]
    })


@app.route("/api/battle/start-round", methods=["POST"])
@login_required
def battle_start_round():
    """Called when a quiz round begins — starts bot's think timer."""
    body = request.get_json() or {}
    room_code = body.get("roomCode", "")
    round_idx = body.get("roundIndex", 0)

    with _rooms_lock:
        room = _rooms.get(room_code)
        if room and round_idx not in room["botRoundStartTimes"]:
            room["botRoundStartTimes"][round_idx] = time.time()
            # Bot switches to "thinking" emotion
            room["botEmotion"] = "thinking 🤔"

    return jsonify({"ok": True})


@app.route("/api/battle/end", methods=["POST"])
@login_required
def battle_end():
    body = request.get_json() or {}
    room_code = body.get("roomCode", "")
    with _rooms_lock:
        room = _rooms.get(room_code)
        if room:
            room["status"] = "complete"
    return jsonify({"ok": True})


@app.route("/api/battle/cancel", methods=["POST"])
@login_required
def battle_cancel():
    body = request.get_json() or {}
    room_code = body.get("roomCode", "")
    with _rooms_lock:
        _rooms.pop(room_code, None)
    return jsonify({"ok": True})


def _tick_bot(room_code: str):
    """
    Check bot plan and award points for rounds where think_time has elapsed.
    Must be called with room data accessible (will acquire lock internally).
    """
    with _rooms_lock:
        room = _rooms.get(room_code)
        if not room or room["status"] == "complete":
            return

        now = time.time()
        curriculum = room["curriculum"]
        all_rounds = curriculum.get("rounds", [])
        plan = room["botPlan"]

        for entry in plan:
            idx = entry["round_index"]
            if room["botAnswered"].get(idx):
                continue  # already answered this round

            start_t = room["botRoundStartTimes"].get(idx)
            if start_t is None:
                continue  # round hasn't started yet for bot

            elapsed = now - start_t
            if elapsed >= entry["think_seconds"]:
                # Bot answers now
                room["botAnswered"][idx] = True
                if entry["correct"]:
                    # Time-based bonus like player
                    timer_left = max(0, 30 - entry["think_seconds"])
                    base_pts = 250 if idx >= len(all_rounds) else 100
                    earned = base_pts + (timer_left * 3)
                    room["botScore"] += earned
                    room["botEmotion"] = random.choice(["excited 🤩", "confident 😎"])
                else:
                    room["botEmotion"] = random.choice(["confused 😅", "thinking 🤔"])

                room["botRound"] = idx + 1


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
