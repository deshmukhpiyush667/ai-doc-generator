from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
import requests
import os
import json
import sqlite3
from datetime import datetime
from functools import wraps
 
app = Flask(__name__)
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
# Auth Helpers
# ──────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
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
# Auth Routes
# ──────────────────────────────────────────────
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))
 
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password)).fetchone()
        if user:
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.")
    return render_template("login.html")
 
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        try:
            with get_db() as db:
                db.execute("INSERT INTO users (name, email, password) VALUES (?,?,?)", (name, email, password))
            flash("Account created! Please log in.")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered.")
    return render_template("signup.html")
 
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
 
# ──────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    uid = session["user_id"]
    chats = db.execute("SELECT * FROM chats WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (uid,)).fetchall()
    docs = db.execute("SELECT * FROM documents WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (uid,)).fetchall()
    chat_count = db.execute("SELECT COUNT(*) FROM chats WHERE user_id=?", (uid,)).fetchone()[0]
    doc_count = db.execute("SELECT COUNT(*) FROM documents WHERE user_id=?", (uid,)).fetchone()[0]
    msg_count = db.execute(
        "SELECT COUNT(*) FROM messages m JOIN chats c ON m.chat_id=c.id WHERE c.user_id=?", (uid,)
    ).fetchone()[0]
    return render_template("dashboard.html",
        chats=chats, docs=docs,
        chat_count=chat_count, doc_count=doc_count, msg_count=msg_count)
 
# ──────────────────────────────────────────────
# Chat Routes
# ──────────────────────────────────────────────
@app.route("/chat")
@login_required
def chat_page():
    db = get_db()
    uid = session["user_id"]
    chats = db.execute("SELECT * FROM chats WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
    return render_template("chat.html", chats=chats, active_chat=None, messages=[])
 
@app.route("/chat/new", methods=["POST"])
@login_required
def new_chat():
    title = request.form.get("title", "New Chat").strip() or "New Chat"
    with get_db() as db:
        cur = db.execute("INSERT INTO chats (user_id, title) VALUES (?,?)", (session["user_id"], title))
        chat_id = cur.lastrowid
    return redirect(url_for("chat_view", chat_id=chat_id))
 
@app.route("/chat/<int:chat_id>")
@login_required
def chat_view(chat_id):
    db = get_db()
    uid = session["user_id"]
    chat = db.execute("SELECT * FROM chats WHERE id=? AND user_id=?", (chat_id, uid)).fetchone()
    if not chat:
        return redirect(url_for("chat_page"))
    chats = db.execute("SELECT * FROM chats WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
    messages = db.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY created_at", (chat_id,)).fetchall()
    return render_template("chat.html", chats=chats, active_chat=chat, messages=messages)
 
@app.route("/chat/<int:chat_id>/send", methods=["POST"])
@login_required
def send_message(chat_id):
    db = get_db()
    uid = session["user_id"]
    chat = db.execute("SELECT * FROM chats WHERE id=? AND user_id=?", (chat_id, uid)).fetchone()
    if not chat:
        return jsonify({"error": "Not found"}), 404
 
    user_msg = request.json.get("message", "").strip()
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400
 
    # Save user message
    with get_db() as d:
        d.execute("INSERT INTO messages (chat_id, role, content) VALUES (?,?,?)", (chat_id, "user", user_msg))
 
    # Build history
    history = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY created_at", (chat_id,)).fetchall()
    msgs = [{"role": r["role"], "content": r["content"]} for r in history]
 
    try:
        ai_reply = call_ai(msgs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
 
    with get_db() as d:
        d.execute("INSERT INTO messages (chat_id, role, content) VALUES (?,?,?)", (chat_id, "assistant", ai_reply))
 
    return jsonify({"reply": ai_reply})
 
@app.route("/chat/<int:chat_id>/delete", methods=["POST"])
@login_required
def delete_chat(chat_id):
    with get_db() as db:
        db.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
        db.execute("DELETE FROM chats WHERE id=? AND user_id=?", (chat_id, session["user_id"]))
    return redirect(url_for("chat_page"))
 
# ──────────────────────────────────────────────
# Document Generation
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
 
@app.route("/documents")
@login_required
def documents_page():
    db = get_db()
    uid = session["user_id"]
    docs = db.execute("SELECT * FROM documents WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
    return render_template("documents.html", docs=docs, doc_types=DOC_TYPES)
 
@app.route("/documents/generate", methods=["GET", "POST"])
@login_required
def generate_doc():
    doc_type = request.args.get("type") or request.form.get("doc_type", "nda")
    if doc_type not in DOC_TYPES:
        doc_type = "nda"
 
    if request.method == "POST":
        details = request.form.get("details", "")
        doc_label = DOC_TYPES[doc_type]
 
        system_prompt = f"""You are a professional legal and business document writer. 
Generate a complete, professional {doc_label} based on the user's details.
Format it clearly with proper sections, headings, and placeholder fields in [BRACKETS] where specific info is needed.
Make it legally sound, comprehensive, and ready to use."""
 
        try:
            content = call_ai(
                [{"role": "user", "content": f"Generate a {doc_label} with these details:\n\n{details}"}],
                system=system_prompt
            )
            title = f"{doc_label} — {datetime.now().strftime('%b %d, %Y')}"
            with get_db() as db:
                db.execute(
                    "INSERT INTO documents (user_id, doc_type, title, content) VALUES (?,?,?,?)",
                    (session["user_id"], doc_type, title, content)
                )
            flash(f"{doc_label} generated successfully!")
            docs = get_db().execute("SELECT * FROM documents WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (session["user_id"],)).fetchone()
            return redirect(url_for("view_doc", doc_id=docs["id"]))
        except Exception as e:
            flash(f"Error generating document: {str(e)}")
 
    return render_template("generate_doc.html", doc_type=doc_type, doc_types=DOC_TYPES)
 
@app.route("/documents/<int:doc_id>")
@login_required
def view_doc(doc_id):
    db = get_db()
    doc = db.execute("SELECT * FROM documents WHERE id=? AND user_id=?", (doc_id, session["user_id"])).fetchone()
    if not doc:
        return redirect(url_for("documents_page"))
    return render_template("view_doc.html", doc=doc, doc_types=DOC_TYPES)
 
@app.route("/documents/<int:doc_id>/delete", methods=["POST"])
@login_required
def delete_doc(doc_id):
    with get_db() as db:
        db.execute("DELETE FROM documents WHERE id=? AND user_id=?", (doc_id, session["user_id"]))
    return redirect(url_for("documents_page"))
 
if __name__ == "__main__":
    app.run(debug=True)