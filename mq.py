import streamlit as st
import os
import random
import time
import tempfile
import zipfile
from datetime import datetime
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# ─────────────────────────────────────────────────────────────
# CONTENT POOLS
# ─────────────────────────────────────────────────────────────
PROVERBS = [
    ("Actions speak louder than words.",   "Give a real-life example where someone's actions mattered more than what they said."),
    ("Every cloud has a silver lining.",    "Describe a time when something bad turned into something good."),
    ("The early bird catches the worm.",    "Do you agree? Share an example from your own life."),
    ("Don't judge a book by its cover.",    "Talk about a time you or someone else misjudged a person or situation."),
    ("A stitch in time saves nine.",        "Describe a situation where acting early would have prevented a bigger problem."),
    ("Birds of a feather flock together.",  "What does this say about human nature? Do you agree?"),
]

WORD_FLOW_WORDS = [
    "Mirror","Freedom","Ocean","Shadow","Journey",
    "Clock","Window","Bridge","Fire","Storm",
    "Home","Dream","Root","Voice","Light",
]

MEMORY_WORD_SETS = [
    ["Tree","Glass","Train","Yellow"],
    ["Apple","River","Chair","Purple"],
    ["Moon","Pencil","Shoe","Bright"],
    ["Dog","Candle","Paper","Thunder"],
    ["Key","Mountain","Bottle","Silver"],
]

EMOTION_SETS = [
    {"name":"Set 1","sentences":[
        ("Calm",      "The night is quiet, and everything feels peaceful around us."),
        ("Anger",     "I told you again and again not to touch it! Why didn't you listen?!"),
        ("Fear",      "Wait... don't move... I think something is right behind us."),
        ("Happiness", "Yes! We actually won! This is incredible!"),
    ]},
    {"name":"Set 2","sentences":[
        ("Calm",      "The soft wind and the quiet trees make this place feel very relaxing."),
        ("Anger",     "This is unbelievable! How could you ruin everything like this?!"),
        ("Fear",      "Please help me... I'm really scared right now."),
        ("Happiness", "I can't believe it! I'm so excited!"),
    ]},
    {"name":"Set 3","sentences":[
        ("Calm",      "The gentle sound of the water makes everything feel calm and slow."),
        ("Anger",     "Enough! I'm tired of repeating the same thing over and over!"),
        ("Fear",      "Did you hear that noise? Something is definitely not right!"),
        ("Happiness", "This is the best day of my life!"),
    ]},
    {"name":"Set 4","sentences":[
        ("Calm",      "The morning air is cool and the world feels very peaceful."),
        ("Anger",     "Why do you never listen to what I say?!"),
        ("Fear",      "Oh no... someone is coming... what should we do?"),
        ("Happiness", "Wow! This is amazing news!"),
    ]},
    {"name":"Set 5","sentences":[
        ("Calm",      "Everything is quiet here, and the atmosphere feels very peaceful."),
        ("Anger",     "I warned you so many times! Now look what you've done!"),
        ("Fear",      "Don't leave me here alone... I'm really frightened."),
        ("Happiness", "We did it! I'm so happy I could shout!"),
    ]},
]

EMOTION_COLORS = {"Calm":"#00f5ff","Anger":"#ff2d78","Fear":"#b347ff","Happiness":"#39ff14"}
EMOTION_ICONS  = {"Calm":"🌊","Anger":"🔥","Fear":"😨","Happiness":"🎉"}

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG & CSS
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="MindQuest", page_icon="🧠", layout="centered")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Exo+2:wght@300;400;600&display=swap');
:root{--neon-purple:#b347ff;--neon-cyan:#00f5ff;--neon-green:#39ff14;--neon-pink:#ff2d78;--dark-bg:#070714;--card-bg:rgba(15,12,41,0.9);}
.stApp{background:var(--dark-bg);background-image:radial-gradient(ellipse at 20% 50%,rgba(100,0,255,0.15) 0%,transparent 60%),radial-gradient(ellipse at 80% 20%,rgba(0,200,255,0.1) 0%,transparent 50%);font-family:'Exo 2',sans-serif;color:#e0e0ff;}
h1,h2,h3{font-family:'Orbitron',sans-serif!important;}
.game-title{font-family:'Orbitron',sans-serif;font-size:2.8rem;font-weight:900;text-align:center;background:linear-gradient(135deg,var(--neon-cyan),var(--neon-purple),var(--neon-pink));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;letter-spacing:3px;filter:drop-shadow(0 0 20px rgba(179,71,255,0.5));margin-bottom:0.2rem;}
.game-subtitle{text-align:center;color:#8888bb;font-size:1rem;letter-spacing:4px;text-transform:uppercase;margin-bottom:2rem;}
.level-card{background:var(--card-bg);border:1px solid rgba(179,71,255,0.3);border-radius:16px;padding:2rem;margin:1rem 0;box-shadow:0 0 30px rgba(179,71,255,0.1),inset 0 0 30px rgba(0,0,0,0.3);position:relative;overflow:hidden;}
.level-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--neon-purple),var(--neon-cyan),transparent);}
.level-badge{display:inline-block;background:linear-gradient(135deg,var(--neon-purple),var(--neon-cyan));color:#000;font-family:'Orbitron',sans-serif;font-weight:700;font-size:0.75rem;padding:4px 14px;border-radius:20px;letter-spacing:2px;margin-bottom:0.8rem;}
.level-title{font-family:'Orbitron',sans-serif;font-size:1.3rem;font-weight:700;color:var(--neon-cyan);margin:0.3rem 0 1rem 0;}
.prompt-box{background:rgba(0,245,255,0.05);border-left:3px solid var(--neon-cyan);padding:1rem 1.2rem;border-radius:0 8px 8px 0;margin:1rem 0;font-size:1.05rem;color:#d0d8ff;line-height:1.6;}
.mq-timer{font-family:'Orbitron',sans-serif;font-size:3rem;font-weight:900;text-align:center;padding:1rem;border-radius:12px;margin:1rem 0;transition:color .4s,background .4s,border-color .4s;}
.mq-timer.idle{color:#8888bb;border:1px dashed rgba(136,136,187,0.3);background:transparent;font-size:1rem;padding:0.7rem;letter-spacing:1px;}
.mq-timer.active{color:var(--neon-green);text-shadow:0 0 20px rgba(57,255,20,0.6);background:rgba(57,255,20,0.05);border:1px solid rgba(57,255,20,0.3);}
.mq-timer.warning{color:#ffaa00;text-shadow:0 0 20px rgba(255,170,0,0.6);background:rgba(255,170,0,0.05);border:1px solid rgba(255,170,0,0.3);}
.mq-timer.danger{color:var(--neon-pink);text-shadow:0 0 20px rgba(255,45,120,0.6);background:rgba(255,45,120,0.05);border:1px solid rgba(255,45,120,0.3);}
.memory-word{font-family:'Orbitron',sans-serif;font-size:1.8rem;font-weight:700;text-align:center;color:var(--neon-cyan);letter-spacing:4px;background:rgba(0,245,255,0.05);border:1px solid rgba(0,245,255,0.2);border-radius:12px;padding:1.5rem;margin:0.5rem 0;text-shadow:0 0 15px rgba(0,245,255,0.5);}
.flash-hidden{font-family:'Orbitron',sans-serif;font-size:1.1rem;text-align:center;color:rgba(179,71,255,0.4);letter-spacing:4px;padding:1.2rem;border:1px dashed rgba(179,71,255,0.2);border-radius:12px;}
.emotion-card{border-radius:14px;padding:1.5rem;margin:0.8rem 0;text-align:center;}
.emotion-label{font-family:'Orbitron',sans-serif;font-size:1rem;font-weight:700;letter-spacing:3px;text-transform:uppercase;margin-bottom:0.6rem;}
.emotion-sentence{font-size:1.15rem;line-height:1.7;color:#e8e8ff;font-style:italic;padding:0 0.5rem;}
.result-card{background:linear-gradient(135deg,rgba(179,71,255,0.15),rgba(0,245,255,0.1));border:1px solid rgba(179,71,255,0.4);border-radius:16px;padding:2.5rem;text-align:center;margin:1rem 0;}
.result-stat{display:flex;justify-content:space-between;align-items:center;padding:0.7rem 0;border-bottom:1px solid rgba(255,255,255,0.07);}
.result-stat:last-child{border-bottom:none;}
.stat-label{color:#8888bb;}.stat-value{font-weight:600;color:var(--neon-cyan);font-family:'Orbitron',sans-serif;font-size:0.85rem;}
.progress-bar-container{display:flex;gap:8px;margin:1rem 0;justify-content:center;}
.progress-dot{width:28px;height:6px;border-radius:3px;background:rgba(255,255,255,0.1);}
.progress-dot.completed{background:linear-gradient(90deg,var(--neon-purple),var(--neon-cyan));box-shadow:0 0 8px rgba(0,245,255,0.5);}
.progress-dot.active{background:var(--neon-cyan);box-shadow:0 0 10px rgba(0,245,255,0.8);animation:pulse 1s infinite;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.consent-box{background:rgba(57,255,20,0.05);border:1px solid rgba(57,255,20,0.2);border-radius:12px;padding:1.2rem 1.5rem;font-size:0.9rem;color:#a0ffb0;margin:1rem 0;}
.stButton>button{background:linear-gradient(135deg,var(--neon-purple),#5500cc)!important;color:white!important;border:none!important;border-radius:8px!important;font-family:'Orbitron',sans-serif!important;font-size:0.8rem!important;letter-spacing:2px!important;padding:0.6rem 1.5rem!important;box-shadow:0 0 15px rgba(179,71,255,0.3)!important;}
.stButton>button:hover{box-shadow:0 0 25px rgba(179,71,255,0.6)!important;transform:translateY(-1px)!important;}
.stTextInput>div>div>input{background:rgba(255,255,255,0.05)!important;border:1px solid rgba(179,71,255,0.3)!important;color:#e0e0ff!important;border-radius:8px!important;font-family:'Exo 2',sans-serif!important;}
hr{border-color:rgba(179,71,255,0.15)!important;}
div[data-testid="stSuccess"]{background:rgba(57,255,20,0.08)!important;border:1px solid rgba(57,255,20,0.3)!important;border-radius:10px!important;}
.mic-hint{text-align:center;color:#8888bb;font-size:0.95rem;padding:0.4rem 0;}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# JS BROWSER TIMER
# ─────────────────────────────────────────────────────────────
import streamlit.components.v1 as components

def js_timer(seconds: int, uid: str):
    half   = seconds // 2
    danger = max(seconds // 6, 5)
    components.html(f"""
    <div id="tmr_{uid}" class="mq-timer idle" style="
        font-family:'Orbitron',monospace;font-size:1rem;font-weight:900;
        text-align:center;padding:0.7rem;border-radius:12px;margin:0.5rem 0;
        color:#8888bb;border:1px dashed rgba(136,136,187,0.3);
        transition:color .4s,background .4s,border-color .4s;letter-spacing:1px;">
      🎤 Click the mic below — timer starts when you do
    </div>
    <script>
    (function(){{
      const DIV   = document.getElementById("tmr_{uid}");
      const TOTAL = {seconds};
      const HALF  = {half};
      const DANGER= {danger};
      let started=false, left=TOTAL, iv=null;

      const fmt = s => {{
        const m=Math.floor(s/60), sec=s%60;
        return (m?"0"+m+":":"00:")+(sec<10?"0"+sec:sec);
      }};

      const paint = () => {{
        DIV.textContent = fmt(left);
        if (left > HALF) {{
          DIV.style.cssText = "font-family:'Orbitron',monospace;font-size:3rem;font-weight:900;text-align:center;padding:1rem;border-radius:12px;margin:0.5rem 0;color:#39ff14;text-shadow:0 0 20px rgba(57,255,20,0.6);background:rgba(57,255,20,0.05);border:1px solid rgba(57,255,20,0.3);transition:all .4s;";
        }} else if (left > DANGER) {{
          DIV.style.cssText = "font-family:'Orbitron',monospace;font-size:3rem;font-weight:900;text-align:center;padding:1rem;border-radius:12px;margin:0.5rem 0;color:#ffaa00;text-shadow:0 0 20px rgba(255,170,0,0.6);background:rgba(255,170,0,0.05);border:1px solid rgba(255,170,0,0.3);transition:all .4s;";
        }} else {{
          DIV.style.cssText = "font-family:'Orbitron',monospace;font-size:3rem;font-weight:900;text-align:center;padding:1rem;border-radius:12px;margin:0.5rem 0;color:#ff2d78;text-shadow:0 0 20px rgba(255,45,120,0.6);background:rgba(255,45,120,0.05);border:1px solid rgba(255,45,120,0.3);transition:all .4s;";
        }}
      }};

      const start = () => {{
        if (started) return;
        started = true;
        paint();
        iv = setInterval(() => {{
          left--;
          if (left <= 0) {{
            clearInterval(iv);
            DIV.textContent = "⏰ TIME'S UP — click ⏹ to save";
            DIV.style.cssText = "font-family:'Orbitron',monospace;font-size:1.2rem;font-weight:900;text-align:center;padding:1rem;border-radius:12px;margin:0.5rem 0;color:#ff2d78;background:rgba(255,45,120,0.05);border:1px solid rgba(255,45,120,0.3);";
          }} else {{ paint(); }}
        }}, 1000);
      }};

      document.addEventListener("click", function(e) {{
        const el = e.target.closest("button");
        if (!el) return;
        const txt = (el.innerText || "").toLowerCase();
        if (txt.includes("record") || txt.includes("start") || txt.includes("mic")) {{
          setTimeout(start, 300);
        }}
      }});
    }})();
    </script>
    """, height=120)


# ─────────────────────────────────────────────────────────────
# GOOGLE DRIVE AUTH
# ─────────────────────────────────────────────────────────────
SCOPES             = ['https://www.googleapis.com/auth/drive.file']
FOLDER_NAME        = "MindQuest_Data"
TOKEN_FILE         = "token.pickle"
CLIENT_SECRET_FILE = "oauth_client.json"

def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'rb') as f:
                creds = pickle.load(f)
        except Exception:
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None
            try: os.remove(TOKEN_FILE)
            except: pass

    if not creds or not creds.valid:
        flow  = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'wb') as f:
            pickle.dump(creds, f)

    return build('drive', 'v3', credentials=creds)

if "drive_ready" not in st.session_state:
    svc = get_drive_service()
    q   = f"name='{FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    res = svc.files().list(q=q, fields="files(id)").execute().get('files', [])
    fid = res[0]['id'] if res else svc.files().create(
            body={'name': FOLDER_NAME, 'mimeType': 'application/vnd.google-apps.folder'},
            fields='id').execute()['id']
    st.session_state.drive_service = svc
    st.session_state.folder_id     = fid
    st.session_state.drive_ready   = True

drive_service = st.session_state.drive_service
folder_id     = st.session_state.folder_id


# ─────────────────────────────────────────────────────────────
# AUDIO STORAGE  — save in memory, zip & upload at the end
# ─────────────────────────────────────────────────────────────
def store_audio(audio_bytes, label, pid):
    """Save audio bytes into session state. No Drive upload yet."""
    if "audio_store" not in st.session_state:
        st.session_state.audio_store = {}
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"{pid}_{label}_{ts}.wav"
    # Store as list [filename, bytes] — lists are hashable-safe in session state
    st.session_state.audio_store[label] = [name, audio_bytes]
    return name


def upload_zip_to_drive(pid):
    """Zip all stored audio and upload one file to Drive safely."""
    store = st.session_state.get("audio_store", {})
    if not store:
        return None

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{pid}_session_{ts}.zip"

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        zip_path = tmp.name

    try:
        # create zip
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for label, (fname, audio_bytes) in store.items():
                zf.writestr(fname, audio_bytes)

        # ⭐ resumable upload (prevents SSL EOF error)
        media = MediaFileUpload(
            zip_path,
            mimetype="application/zip",
            resumable=True,
            chunksize=1024 * 1024
        )

        request = drive_service.files().create(
            body={'name': zip_name, 'parents': [folder_id]},
            media_body=media,
            fields='id'
        )

        response = None
        while response is None:
            status, response = request.next_chunk()

    finally:
        try:
            os.remove(zip_path)
        except:
            pass

    return zip_name


# ─────────────────────────────────────────────────────────────
# SESSION DEFAULTS
# ─────────────────────────────────────────────────────────────
def _ss(k, v):
    if k not in st.session_state: st.session_state[k] = v

_ss("game_level",   0)
_ss("pid",          "")
_ss("uploads",      {})
_ss("audio_store",  {})
_ss("proverb",      random.choice(PROVERBS))
_ss("wf_words",     random.sample(WORD_FLOW_WORDS, 2))
_ss("mem_words",    random.choice(MEMORY_WORD_SETS))
_ss("emotion_set",  random.choice(EMOTION_SETS))
_ss("words_shown",  False)
_ss("words_hidden", False)
_ss("l3_round",     "A")
_ss("l6_idx",       0)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def progress_bar(cur, total=6):
    dots = "".join(
        f'<div class="progress-dot {"completed" if i<cur else "active" if i==cur else ""}"></div>'
        for i in range(1, total+1))
    st.markdown(f'<div class="progress-bar-container">{dots}</div>', unsafe_allow_html=True)

def mic_hint():
    st.markdown('<div class="mic-hint">🎙️ Click the <strong style="color:#00f5ff">mic button</strong> below to record</div>', unsafe_allow_html=True)

def try_save(audio, label):
    """Store audio in memory once; return True when done."""
    if audio and label not in st.session_state.uploads:
        with st.spinner("Saving audio…"):
            st.session_state.uploads[label] = store_audio(
                audio.getvalue(), label, st.session_state.pid)
        st.rerun()
    return label in st.session_state.uploads

def next_btn(text, key, next_level=None, extra_fn=None):
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        if st.button(text, use_container_width=True, key=key):
            if extra_fn: extra_fn()
            if next_level is not None: st.session_state.game_level = next_level
            st.rerun()


# ─────────────────────────────────────────────────────────────
# TITLE
# ─────────────────────────────────────────────────────────────
st.markdown('<div class="game-title">MIND QUEST</div>', unsafe_allow_html=True)
st.markdown('<div class="game-subtitle">How Does Your Brain Speak?</div>', unsafe_allow_html=True)

lvl = st.session_state.game_level

# ═══════════════════════════
# 0 — REGISTRATION
# ═══════════════════════════
if lvl == 0:
    st.markdown("""
    <div class="level-card">
        <div class="level-badge">🔐 BEFORE WE BEGIN</div>
        <div class="level-title">Welcome, Explorer</div>
    </div>""", unsafe_allow_html=True)
    st.markdown("""
    <div class="consent-box">
    🧪 <strong>Research Notice</strong><br>
    This is a speech-pattern research demo. Your audio will be recorded <em>anonymously</em>
    and used solely for academic research purposes. By participating you consent to this recording.
    </div>""", unsafe_allow_html=True)
    st.markdown("""
    <div class="level-card">
    🎮 <strong>6 fun brain challenges</strong> &nbsp;·&nbsp; ~6 min total &nbsp;·&nbsp; No wrong answers<br><br>
    <em>Just speak naturally. The more expressive, the better!</em>
    </div>""", unsafe_allow_html=True)
    pid_in = st.text_input("**Enter your Participant ID**", placeholder="e.g. P01, P02 …")
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        if st.button("🚀  LAUNCH GAME", use_container_width=True):
            if pid_in.strip():
                st.session_state.pid = pid_in.strip()
                st.session_state.game_level = 1
                st.rerun()
            else:
                st.error("Please enter a Participant ID.")

# ═══════════════════════════
# 1 — DAY IN 60 SECONDS
# ═══════════════════════════
elif lvl == 1:
    progress_bar(1)
    st.markdown(f"""
    <div class="level-card">
        <div class="level-badge">LEVEL 1 · NARRATIVE</div>
        <div class="level-title">🎬 Day-in-60 Challenge</div>
        <div class="prompt-box">
            Describe your typical day from <strong>morning to night</strong>.
            Be as detailed as possible — routines, meals, thoughts, feelings, everything!<br><br>
            <em>🌟 You have 90 seconds. The more vivid, the better your score!</em>
        </div>
    </div>""", unsafe_allow_html=True)
    st.markdown(f"<div style='text-align:right;color:#8888bb;font-size:0.9rem;'>Participant: <strong style='color:#00f5ff'>{st.session_state.pid}</strong></div>", unsafe_allow_html=True)

    if "L1" not in st.session_state.uploads:
        js_timer(90, "l1")
        mic_hint()
        audio = st.audio_input("L1", label_visibility="collapsed", key="rec_l1")
        try_save(audio, "L1")
    else:
        st.success("✅ Coherence Meter: **STRONG** 📈")
        next_btn("NEXT LEVEL →", "l1_nx", next_level=2)

# ═══════════════════════════
# 2 — MEANING MASTER
# ═══════════════════════════
elif lvl == 2:
    progress_bar(2)
    prov_text, prov_q = st.session_state.proverb
    st.markdown(f"""
    <div class="level-card">
        <div class="level-badge">LEVEL 2 · ABSTRACT THINKING</div>
        <div class="level-title">🧩 Meaning Master</div>
        <div class="prompt-box">
            <span style="font-size:1.2rem;color:#b347ff;font-weight:600;">"{prov_text}"</span><br><br>
            {prov_q}
        </div>
    </div>""", unsafe_allow_html=True)
    st.markdown("<div style='color:#8888bb;font-size:0.85rem;'>🏅 Earn the <strong style='color:#ffaa00'>Deep Thinker</strong> badge!</div>", unsafe_allow_html=True)

    if "L2" not in st.session_state.uploads:
        js_timer(60, "l2")
        mic_hint()
        audio = st.audio_input("L2", label_visibility="collapsed", key="rec_l2")
        try_save(audio, "L2")
    else:
        st.success("✅ **Deep Thinker** badge unlocked 🏅")
        next_btn("NEXT LEVEL →", "l2_nx", next_level=3)

# ═══════════════════════════
# 3 — MIND DRIFT
# ═══════════════════════════
elif lvl == 3:
    progress_bar(3)
    w1, w2 = st.session_state.wf_words
    st.markdown("""
    <div class="level-card">
        <div class="level-badge">LEVEL 3 · FREE ASSOCIATION</div>
        <div class="level-title">🔄 Mind Drift</div>
        <div class="prompt-box">
            A word will appear. Speak about <strong>anything related to it</strong> for 30 s each.<br>
            No rules. No wrong answers. Let your thoughts flow freely!<br><br>
            <em>⚡ Thought Stream Mode — Activated</em>
        </div>
    </div>""", unsafe_allow_html=True)

    if st.session_state.l3_round == "A":
        st.markdown("---")
        st.markdown("#### 🔵 Round A · Your Word:")
        st.markdown(f'<div class="memory-word" style="color:#b347ff;border-color:rgba(179,71,255,0.4);text-shadow:0 0 15px rgba(179,71,255,0.6);">{w1.upper()}</div>', unsafe_allow_html=True)
        if "L3A" not in st.session_state.uploads:
            js_timer(30, "l3a")
            mic_hint()
            audio = st.audio_input("L3A", label_visibility="collapsed", key="rec_l3a")
            try_save(audio, "L3A")
        else:
            st.success("✅ Round A saved!")
            def _to_b(): st.session_state.l3_round = "B"
            next_btn("➡  CONTINUE TO ROUND B", "l3_toB", extra_fn=_to_b)

    elif st.session_state.l3_round == "B":
        st.markdown("---")
        st.markdown("#### 🟢 Round B · Your Word:")
        st.markdown(f'<div class="memory-word" style="color:#00f5ff;">{w2.upper()}</div>', unsafe_allow_html=True)
        if "L3B" not in st.session_state.uploads:
            js_timer(30, "l3b")
            mic_hint()
            audio = st.audio_input("L3B", label_visibility="collapsed", key="rec_l3b")
            try_save(audio, "L3B")
        else:
            st.success("✅ Round B saved! Association Style: **Divergent** 🌊")
            next_btn("NEXT LEVEL →", "l3_nx", next_level=4)

# ═══════════════════════════
# 4 — EMOTION MODE
# ═══════════════════════════
elif lvl == 4:
    progress_bar(4)
    st.markdown("""
    <div class="level-card">
        <div class="level-badge">LEVEL 4 · EMOTION</div>
        <div class="level-title">🎭 Emotion Mode</div>
        <div class="prompt-box">
            Describe a <strong>stressful moment</strong> in your life —
            what happened, how you felt, and how you got through it.<br><br>
            <em>🎯 Emotional Depth Score: Recording in progress…</em>
        </div>
    </div>""", unsafe_allow_html=True)
    st.markdown("<div style='color:#8888bb;font-size:0.85rem;'>💡 The more expressive, the better!</div>", unsafe_allow_html=True)

    if "L4" not in st.session_state.uploads:
        js_timer(60, "l4")
        mic_hint()
        audio = st.audio_input("L4", label_visibility="collapsed", key="rec_l4")
        try_save(audio, "L4")
    else:
        st.success("✅ Emotional Depth Score: **HIGH** 🎭")
        next_btn("NEXT LEVEL →", "l4_nx", next_level=5)

# ═══════════════════════════
# 5 — MEMORY UNDER PRESSURE
# ═══════════════════════════
elif lvl == 5:
    progress_bar(5)
    mem = st.session_state.mem_words
    st.markdown("""
    <div class="level-card">
        <div class="level-badge">LEVEL 5 · MEMORY + COGNITION</div>
        <div class="level-title">🧠 Memory Under Pressure</div>
        <div class="prompt-box">
            <strong>Step 1:</strong> Memorize the words below (vanish in 5 s!)<br>
            <strong>Step 2:</strong> Talk about <em>social media</em> for 40 seconds.<br>
            <strong>Step 3:</strong> Recall the 4 words out loud.<br><br>
            <em>🔴 Brain Load Mode — Activated</em>
        </div>
    </div>""", unsafe_allow_html=True)

    st.markdown("#### 📋 Memorize These Words:")

    if not st.session_state.words_shown and not st.session_state.words_hidden:
        if st.button("👁  SHOW WORDS (5 seconds)", key="show_w"):
            st.session_state.words_shown = True
            st.rerun()

    if st.session_state.words_shown and not st.session_state.words_hidden:
        ph = st.empty(); cd = st.empty()
        ph.markdown(f'<div class="memory-word">{" &nbsp;·&nbsp; ".join(mem)}</div>', unsafe_allow_html=True)
        for i in range(5, 0, -1):
            cd.markdown(f'<div style="text-align:center;color:#ffaa00;font-family:Orbitron;font-size:1rem;">Hiding in {i}s…</div>', unsafe_allow_html=True)
            time.sleep(1)
        ph.markdown('<div class="flash-hidden">[ WORDS HIDDEN — RECALL AT END ]</div>', unsafe_allow_html=True)
        cd.empty()
        st.session_state.words_hidden = True
        st.session_state.words_shown  = False
        st.rerun()

    if st.session_state.words_hidden:
        st.markdown('<div class="flash-hidden">[ WORDS HIDDEN — RECALL AT END ]</div>', unsafe_allow_html=True)
        st.markdown("---")

        if "L5A" not in st.session_state.uploads:
            st.markdown("#### 🎙️ Part A — Talk about Social Media (40s):")
            js_timer(40, "l5a")
            mic_hint()
            audio = st.audio_input("L5A", label_visibility="collapsed", key="rec_l5a")
            try_save(audio, "L5A")

        if "L5A" in st.session_state.uploads and "L5B" not in st.session_state.uploads:
            st.success("✅ Part A saved!")
            st.markdown("---")
            st.markdown("#### 🔁 Part B — Recall the 4 words out loud:")
            mic_hint()
            audio = st.audio_input("L5B", label_visibility="collapsed", key="rec_l5b")
            try_save(audio, "L5B")

        if "L5B" in st.session_state.uploads:
            st.success("✅ Memory Index: **COMPUTED** 🧩")
            next_btn("NEXT LEVEL →", "l5_nx", next_level=6)

# ═══════════════════════════
# 6 — ACTING CHALLENGE
# ═══════════════════════════
elif lvl == 6:
    progress_bar(6)
    eset  = st.session_state.emotion_set
    sents = eset["sentences"]
    idx   = st.session_state.l6_idx

    st.markdown(f"""
    <div class="level-card">
        <div class="level-badge">LEVEL 6 · EMOTIONAL PROSODY — {eset['name']}</div>
        <div class="level-title">🎭 Acting Challenge</div>
        <div class="prompt-box">
            Read the sentence below <strong>out loud</strong> using the emotion shown.<br>
            Really feel it — exaggerate tone, pitch and intensity!<br><br>
            <em>🎬 Sentence {idx+1} of 4</em>
        </div>
    </div>""", unsafe_allow_html=True)

    if idx < 4:
        emotion, sentence = sents[idx]
        color = EMOTION_COLORS[emotion]
        icon  = EMOTION_ICONS[emotion]
        lbl   = f"L6_{idx}"

        st.markdown(f"""
        <div class="emotion-card" style="background:rgba(0,0,0,0.3);border:2px solid {color}55;">
            <div class="emotion-label" style="color:{color};">{icon} {emotion}</div>
            <div class="emotion-sentence">"{sentence}"</div>
        </div>""", unsafe_allow_html=True)

        if lbl not in st.session_state.uploads:
            js_timer(20, f"l6_{idx}")
            mic_hint()
            audio = st.audio_input(lbl, label_visibility="collapsed", key=f"rec_l6_{idx}")
            try_save(audio, lbl)
        else:
            st.success(f"✅ {emotion} recorded!")
            if idx < 3:
                def _adv(): st.session_state.l6_idx += 1
                next_btn(f"NEXT SENTENCE ({idx+2}/4) →", f"l6_nx_{idx}", extra_fn=_adv)
            else:
                next_btn("🏁  VIEW RESULTS", "l6_done", next_level=7)

    dots = "".join(
        f'<span style="display:inline-block;margin:0 8px;text-align:center;">'
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;'
        f'background:{"" if f"L6_{i}" not in st.session_state.uploads else EMOTION_COLORS[sents[i][0]]};'
        f'border:2px solid {EMOTION_COLORS[sents[i][0]]};"></span>'
        f'<div style="font-size:0.65rem;color:{EMOTION_COLORS[sents[i][0]] if f"L6_{i}" in st.session_state.uploads else "#555"};'
        f'margin-top:3px;">{sents[i][0]}</div></span>'
        for i in range(4))
    st.markdown(f'<div style="text-align:center;margin-top:1rem;">{dots}</div>', unsafe_allow_html=True)

# ═══════════════════════════
# 7 — RESULTS
# ═══════════════════════════
elif lvl == 7:
    st.markdown("""
    <div class="result-card">
        <div style="font-family:Orbitron;font-size:2rem;font-weight:900;
             background:linear-gradient(135deg,#b347ff,#00f5ff,#39ff14);
             -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:0.5rem;">
            🏆 MISSION COMPLETE
        </div>
        <div style="color:#8888bb;font-size:0.9rem;letter-spacing:2px;margin-bottom:1.5rem;">
            BRAIN ANALYSIS REPORT
        </div>
    </div>""", unsafe_allow_html=True)

    results = [
        ("🎬","Narrative Flow",     random.choice(["Strong","Dynamic","Vivid","Eloquent"])),
        ("🧩","Abstract Thinking",  random.choice(["Creative","Deep","Layered","Philosophical"])),
        ("🔄","Association Style",  random.choice(["Divergent","Expansive","Fluid","Rich"])),
        ("🎭","Emotional Depth",    random.choice(["High","Expressive","Resonant","Authentic"])),
        ("⚡","Response Speed",     random.choice(["Fast","Agile","Sharp","Confident"])),
        ("🧠","Memory Performance", random.choice(["Excellent","Precise","Focused","Impressive"])),
        ("🎤","Prosody Range",      random.choice(["Expressive","Varied","Dynamic","Nuanced"])),
    ]
    st.markdown('<div class="level-card">', unsafe_allow_html=True)
    for icon, label, val in results:
        st.markdown(f'<div class="result-stat"><span class="stat-label">{icon} {label}</span><span class="stat-value">{val} ✦</span></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Zip & upload once ──
    if "zip_uploaded" not in st.session_state:
        with st.spinner("📦 Packaging all recordings and uploading to Drive…"):
            zip_name = upload_zip_to_drive(st.session_state.pid)
        st.session_state.zip_uploaded = zip_name or "uploaded"

    n_files = len(st.session_state.get("audio_store", {}))
    st.markdown(f"""
    <div style="text-align:center;margin:1.5rem 0;padding:1rem;background:rgba(57,255,20,0.05);border-radius:12px;border:1px solid rgba(57,255,20,0.2);">
        <div style="font-family:Orbitron;color:#39ff14;font-size:0.9rem;letter-spacing:2px;">✅ SESSION ZIP UPLOADED TO DRIVE</div>
        <div style="color:#a0ffb0;font-size:0.82rem;font-family:monospace;margin-top:0.3rem;">{st.session_state.zip_uploaded}</div>
        <div style="color:#8888bb;font-size:0.8rem;margin-top:0.3rem;">{n_files} recordings packaged into one file</div>
    </div>
    <div style="text-align:center;color:#5555aa;font-size:0.85rem;">Session: {st.session_state.pid} · {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        if st.button("🔄  NEW PARTICIPANT", use_container_width=True):
            keep = {"drive_ready", "drive_service", "folder_id"}
            for k in [k for k in st.session_state if k not in keep]:
                del st.session_state[k]
            st.rerun()