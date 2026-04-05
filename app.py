from flask import Flask, request, jsonify, send_from_directory, session
import requests
import os
import sqlite3
from datetime import datetime
from functools import wraps

app = Flask(__name__, static_folder=".", static_url_path="")
app.secret_key = os.getenv("SECRET_KEY", "change-me-in-production")

DB = "docgen.db"

# ──────────────────────────────────────────────
# Database Setup
# ──────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(chat_id) REFERENCES chats(id)
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            doc_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """)

init_db()

# ──────────────────────────────────────────────
# Auth Helper
# ──────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def call_ai(messages, system=None):
    payload = {
        "model": "arcee-ai/trinity-large-preview:free",
        "messages": messages
    }
    if system:
        payload["messages"] = [{"role": "system", "content": system}] + messages

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60
    )
    data = resp.json()
    return data["choices"][0]["message"]["content"]

# ──────────────────────────────────────────────
# Serve index.html for all non-API routes
# ──────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "index.html")

# ──────────────────────────────────────────────
# Auth API Routes
# ──────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    email    = (data.get("email") or "").strip()
    password = data.get("password") or ""

    db   = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE email=? AND password=?", (email, password)
    ).fetchone()

    if not user:
        return jsonify({"error": "Invalid email or password."}), 401

    session["user_id"]   = user["id"]
    session["user_name"] = user["name"]
    return jsonify({"id": user["id"], "name": user["name"], "email": user["email"]})


@app.route("/api/signup", methods=["POST"])
def api_signup():
    data     = request.get_json()
    name     = (data.get("name") or "").strip()
    email    = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not name or not email or not password:
        return jsonify({"error": "All fields are required."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO users (name, email, password) VALUES (?,?,?)",
                (name, email, password)
            )
        # Auto-login after signup
        db   = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        session["user_id"]   = user["id"]
        session["user_name"] = user["name"]
        return jsonify({"id": user["id"], "name": user["name"], "email": user["email"]}), 201
    except Exception:
        return jsonify({"error": "Email already registered."}), 409


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def api_me():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    db   = get_db()
    user = db.execute("SELECT id, name, email FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"id": user["id"], "name": user["name"], "email": user["email"]})

# ──────────────────────────────────────────────
# Dashboard API
# ──────────────────────────────────────────────
@app.route("/api/dashboard")
@login_required
def api_dashboard():
    db  = get_db()
    uid = session["user_id"]

    chats = db.execute(
        "SELECT id, title, created_at FROM chats WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (uid,)
    ).fetchall()
    docs = db.execute(
        "SELECT id, doc_type, title, created_at FROM documents WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (uid,)
    ).fetchall()
    chat_count = db.execute("SELECT COUNT(*) FROM chats WHERE user_id=?", (uid,)).fetchone()[0]
    doc_count  = db.execute("SELECT COUNT(*) FROM documents WHERE user_id=?", (uid,)).fetchone()[0]
    msg_count  = db.execute(
        "SELECT COUNT(*) FROM messages m JOIN chats c ON m.chat_id=c.id WHERE c.user_id=?", (uid,)
    ).fetchone()[0]

    return jsonify({
        "chat_count": chat_count,
        "doc_count":  doc_count,
        "msg_count":  msg_count,
        "chats": [dict(c) for c in chats],
        "docs":  [dict(d) for d in docs],
    })

# ──────────────────────────────────────────────
# Chat API Routes
# ──────────────────────────────────────────────
@app.route("/api/chats", methods=["GET"])
@login_required
def api_get_chats():
    db    = get_db()
    uid   = session["user_id"]
    chats = db.execute(
        "SELECT id, title, created_at FROM chats WHERE user_id=? ORDER BY created_at DESC", (uid,)
    ).fetchall()
    return jsonify([dict(c) for c in chats])


@app.route("/api/chats", methods=["POST"])
@login_required
def api_new_chat():
    data  = request.get_json()
    title = (data.get("title") or "New Chat").strip() or "New Chat"
    with get_db() as db:
        cur     = db.execute(
            "INSERT INTO chats (user_id, title) VALUES (?,?)", (session["user_id"], title)
        )
        chat_id = cur.lastrowid
    db   = get_db()
    chat = db.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
    return jsonify(dict(chat)), 201


@app.route("/api/chats/<int:chat_id>", methods=["GET"])
@login_required
def api_get_chat(chat_id):
    db   = get_db()
    uid  = session["user_id"]
    chat = db.execute(
        "SELECT * FROM chats WHERE id=? AND user_id=?", (chat_id, uid)
    ).fetchone()
    if not chat:
        return jsonify({"error": "Not found"}), 404
    messages = db.execute(
        "SELECT role, content, created_at FROM messages WHERE chat_id=? ORDER BY created_at", (chat_id,)
    ).fetchall()
    return jsonify({"chat": dict(chat), "messages": [dict(m) for m in messages]})


@app.route("/api/chats/<int:chat_id>/send", methods=["POST"])
@login_required
def api_send_message(chat_id):
    db   = get_db()
    uid  = session["user_id"]
    chat = db.execute(
        "SELECT * FROM chats WHERE id=? AND user_id=?", (chat_id, uid)
    ).fetchone()
    if not chat:
        return jsonify({"error": "Not found"}), 404

    user_msg = (request.get_json().get("message") or "").strip()
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    with get_db() as d:
        d.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?,?,?)",
            (chat_id, "user", user_msg)
        )

    history = db.execute(
        "SELECT role, content FROM messages WHERE chat_id=? ORDER BY created_at", (chat_id,)
    ).fetchall()
    msgs = [{"role": r["role"], "content": r["content"]} for r in history]

    try:
        ai_reply = call_ai(
            msgs,
            system="You are DocGen AI, a helpful assistant specializing in documents, contracts, legal templates, and professional writing."
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    with get_db() as d:
        d.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?,?,?)",
            (chat_id, "assistant", ai_reply)
        )

    return jsonify({"reply": ai_reply})


@app.route("/api/chats/<int:chat_id>", methods=["DELETE"])
@login_required
def api_delete_chat(chat_id):
    with get_db() as db:
        db.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
        db.execute(
            "DELETE FROM chats WHERE id=? AND user_id=?", (chat_id, session["user_id"])
        )
    return jsonify({"ok": True})

# ──────────────────────────────────────────────
# Documents API Routes
# ──────────────────────────────────────────────
DOC_TYPES = {
    "nda": "Non-Disclosure Agreement (NDA)",
    "resume": "Professional Resume / CV",
    "invoice": "Invoice",
    "offer_letter": "Offer Letter",
    "cover_letter": "Cover Letter",
    "employment_contract": "Employment Contract",
    "lease_agreement": "Lease / Rental Agreement",
    "partnership_agreement": "Partnership Agreement",
    "service_agreement": "Service Agreement",
    "privacy_policy": "Privacy Policy",
    "terms_of_service": "Terms of Service",
    "memo": "Business Memo",
    "business_plan": "Business Plan",
    "proposal": "Project Proposal",
    "sow": "Statement of Work (SOW)",
    "mou": "Memorandum of Understanding (MOU)",
    "cease_desist": "Cease & Desist Letter",
    "press_release": "Press Release",
    "meeting_minutes": "Meeting Minutes",
    "performance_review": "Performance Review",
}


@app.route("/api/documents", methods=["GET"])
@login_required
def api_get_documents():
    db   = get_db()
    uid  = session["user_id"]
    docs = db.execute(
        "SELECT * FROM documents WHERE user_id=? ORDER BY created_at DESC", (uid,)
    ).fetchall()
    return jsonify([dict(d) for d in docs])


@app.route("/api/documents/generate", methods=["POST"])
@login_required
def api_generate_doc():
    data     = request.get_json()
    doc_type = data.get("doc_type", "nda")
    details  = (data.get("details") or "").strip()

    if doc_type not in DOC_TYPES:
        doc_type = "nda"
    if not details:
        return jsonify({"error": "Details are required."}), 400

    doc_label     = DOC_TYPES[doc_type]
    system_prompt = (
        f"You are a professional legal and business document writer. "
        f"Generate a complete, professional {doc_label} based on the user's details. "
        f"Format it clearly with proper sections, headings, and placeholder fields in "
        f"[BRACKETS] where specific info is needed. "
        f"Make it legally sound, comprehensive, and ready to use."
    )

    try:
        content = call_ai(
            [{"role": "user", "content": f"Generate a {doc_label} with these details:\n\n{details}"}],
            system=system_prompt
        )
        title = f"{doc_label} — {datetime.now().strftime('%b %d, %Y')}"
        with get_db() as db:
            cur    = db.execute(
                "INSERT INTO documents (user_id, doc_type, title, content) VALUES (?,?,?,?)",
                (session["user_id"], doc_type, title, content)
            )
            doc_id = cur.lastrowid

        db  = get_db()
        doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return jsonify(dict(doc)), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/documents/<int:doc_id>", methods=["GET"])
@login_required
def api_get_doc(doc_id):
    db  = get_db()
    doc = db.execute(
        "SELECT * FROM documents WHERE id=? AND user_id=?", (doc_id, session["user_id"])
    ).fetchone()
    if not doc:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(doc))


@app.route("/api/documents/<int:doc_id>", methods=["DELETE"])
@login_required
def api_delete_doc(doc_id):
    with get_db() as db:
        db.execute(
            "DELETE FROM documents WHERE id=? AND user_id=?", (doc_id, session["user_id"])
        )
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)