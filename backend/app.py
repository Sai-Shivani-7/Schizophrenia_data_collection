import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import joblib
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Depends
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from gdrive_utils import upload_zip_to_drive
from utils import audio_to_text, predict_text
from pymongo import MongoClient
from bson import ObjectId
from jose import JWTError, jwt
from passlib.context import CryptContext
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests


app = FastAPI(title="Multi-Step Audio Session API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "schizo_speech_model.pkl"
RESULTS_DIR = BASE_DIR / "results"
SITE_DIR = BASE_DIR.parent / "audio-collection-site"
QUESTIONS = {1, 2, 3}
AUTO_DELETE_AFTER_UPLOAD = os.getenv("AUTO_DELETE_AFTER_UPLOAD", "false").lower() == "true"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
db_client = MongoClient(MONGO_URI)
db = db_client["schizo_data"]
transcripts_coll = db["transcripts"]
users_coll = db["users"]

# Auth Configuration
SECRET_KEY = "your-secret-key-change-this-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60  # Long-lived for this prototype

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
GOOGLE_CLIENT_ID = "521659328079-fo0ivlcb0vi1e15jh2t60eqn20t9388n.apps.googleusercontent.com"

# Mount the frontend static files so the browser can open the site
# via http://localhost:8000/site/index.html (no file:// security issues)
if SITE_DIR.is_dir():
    app.mount("/site", StaticFiles(directory=str(SITE_DIR), html=True), name="site")

model_state = {
    "model": None,
    "threshold": None,
    "margin": None,
    "features": None,
    "scaler": None,
    "loaded": False,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_question_number(question_number: int) -> int:
    if question_number not in QUESTIONS:
        raise HTTPException(status_code=400, detail="question_number must be 1, 2, or 3.")
    return question_number


def normalize_session_id(session_id: Optional[str]) -> str:
    raw = (session_id or "").strip()
    if not raw:
        raw = uuid.uuid4().hex
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", raw)
    if not safe:
        safe = uuid.uuid4().hex
    return safe[:80]


def session_dir(session_id: str) -> Path:
    return RESULTS_DIR / f"session_{session_id}"


def ensure_session_dirs(root: Path) -> None:
    (root / "recordings").mkdir(parents=True, exist_ok=True)
    (root / "transcripts").mkdir(parents=True, exist_ok=True)
    (root / "results").mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def question_transcript_path(root: Path, question_number: int) -> Path:
    return root / "transcripts" / f"q{question_number}.txt"


def combined_transcript_path(root: Path, question_number: int) -> Path:
    return root / "transcripts" / f"combined_upto_q{question_number}.txt"


def require_prior_transcripts(root: Path, question_number: int) -> None:
    missing = [
        f"q{i}.txt"
        for i in range(1, question_number)
        if not question_transcript_path(root, i).exists()
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing previous transcript(s): {', '.join(missing)}. Complete questions in Q1 -> Q2 -> Q3 order.",
        )


def build_combined_transcript(session_id: str, question_number: int) -> str:
    session_dir = RESULTS_DIR / f"session_{session_id}"
    combined_text = ""
    found_any = False
    
    # Try preferred structure: session_dir/transcripts/qX_transcript.txt
    for i in range(1, question_number + 1):
        transcript_path = session_dir / "transcripts" / f"q{i}_transcript.txt"
        if transcript_path.exists():
            found_any = True
            content = transcript_path.read_text(encoding="utf-8").strip()
            combined_text += f"--- STEP {i} ---\n{content}\n\n"
    
    if not found_any:
        # Fallback to session_dir/qX_transcript.txt
        for i in range(1, question_number + 1):
            transcript_path = session_dir / f"q{i}_transcript.txt"
            if transcript_path.exists():
                content = transcript_path.read_text(encoding="utf-8").strip()
                combined_text += f"--- STEP {i} ---\n{content}\n\n"
                
    return combined_text.strip()


def session_zip_path(root: Path, session_id: str) -> Path:
    return root.with_name(f"session_{session_id}.zip")


def zip_session_folder(root: Path, session_id: str) -> Path:
    zip_path = session_zip_path(root, session_id)
    if zip_path.exists():
        zip_path.unlink()

    archive_base = root.with_suffix("")
    created_zip = shutil.make_archive(str(archive_base), "zip", root_dir=root)
    created_path = Path(created_zip)
    if created_path != zip_path:
        created_path.replace(zip_path)
    return zip_path


def list_existing_question_files(root: Path, folder: str, suffix: str) -> list[str]:
    target = root / folder
    return [
        f"q{i}{suffix}"
        for i in sorted(QUESTIONS)
        if (target / f"q{i}{suffix}").exists()
    ]


def load_metadata(root: Path, session_id: str) -> dict:
    metadata_path = root / "metadata.json"
    if metadata_path.exists():
        try:
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    return {
        "session_id": session_id,
        "questions_completed": 0,
        "files": {
            "recordings": [],
            "transcripts": [],
            "combined_used": None,
        },
        "last_updated": now_iso(),
    }


def save_metadata(root: Path, session_id: str, combined_used: Optional[str] = None, drive_link: Optional[str] = None) -> dict:
    metadata = load_metadata(root, session_id)
    transcripts = list_existing_question_files(root, "transcripts", ".txt")
    recordings = list_existing_question_files(root, "recordings", ".wav")

    metadata["session_id"] = session_id
    metadata["questions_completed"] = len(transcripts)
    metadata["files"] = {
        "recordings": recordings,
        "transcripts": transcripts,
        "combined_used": combined_used or metadata.get("files", {}).get("combined_used"),
    }
    if drive_link:
        metadata["drive_download_link"] = drive_link
    metadata["last_updated"] = now_iso()

    (root / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def ensure_model_loaded() -> None:
    if not model_state["loaded"]:
        raise HTTPException(status_code=500, detail="Model checkpoint not loaded on server.")


def report_payload(session_id: str, question_number: int, combined_name: str, combined_text: str, prediction: dict) -> dict:
    return {
        "session_id": session_id,
        "question_number": question_number,
        "model_input_rule": "combined transcript up to current question",
        "model_input_file": combined_name,
        "model_input_text": combined_text,
        "generated_at": now_iso(),
        "prediction": prediction["label_str"],
        "probability": prediction["prob_schiz"],
        "threshold": prediction.get("threshold"),
        "margin": prediction.get("margin"),
        "biomarkers": prediction["biomarkers"],
        "triggered": prediction.get("triggered", []),
        "report": prediction["report"],
    }


@app.on_event("startup")
def load_model() -> None:
    if not MODEL_PATH.exists():
        print(f"WARNING: Model file not found at {MODEL_PATH}")
        return

    try:
        ckpt = joblib.load(MODEL_PATH)
        model_state["model"] = ckpt["model"]
        model_state["threshold"] = ckpt["threshold"]
        model_state["margin"] = ckpt["margin"]
        model_state["features"] = ckpt["features"]
        model_state["scaler"] = ckpt["scaler"]
        model_state["loaded"] = True
        print(f"SUCCESS: Model checkpoint loaded successfully from {MODEL_PATH}")
    except Exception as exc:
        print(f"ERROR: Error loading model checkpoint: {exc}")

    # MongoDB Connection Check
    try:
        db_client.admin.command('ping')
        print(f"SUCCESS: Connected to MongoDB at {MONGO_URI}")
    except Exception as exc:
        print(f"ERROR: Failed to connect to MongoDB: {exc}")

    # Seed Admin Accounts
    admins = [
        {"email": "admin@mindquest.com", "password": "admin123", "name": "Main Admin"},
        {"email": "madhavisrinivasskb@gmail.com", "password": "adminpassword", "name": "Madhavi Admin"}, # Adding user as admin
        {"email": "research@mindquest.com", "password": "research2024", "name": "Research Admin"}
    ]
    
    for admin in admins:
        if not users_coll.find_one({"email": admin["email"]}):
            hashed_pw = pwd_context.hash(admin["password"])
            users_coll.insert_one({
                "email": admin["email"],
                "password": hashed_pw,
                "role": "admin",
                "name": admin["name"],
                "created_at": now_iso()
            })
            print(f"SUCCESS: Admin created: {admin['email']}")


# --- Authentication Helpers ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)

def create_access_token(data: dict):
    to_encode = data.copy()
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        # Some browsers/clients might send "Bearer undefined" if not logged in
        if token == "undefined":
            raise HTTPException(status_code=401, detail="Invalid token")
            
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Could not validate credentials")
        user = users_coll.find_one({"email": email})
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        user["_id"] = str(user["_id"])
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")


# --- Auth Endpoints ---

@app.post("/api/auth/signup")
async def signup(email: str = Form(...), password: str = Form(...), name: str = Form(...), role: str = Form("user")):
    if users_coll.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = pwd_context.hash(password)
    user_doc = {
        "email": email,
        "password": hashed_password,
        "name": name,
        "role": role, # Default is user
        "created_at": now_iso()
    }
    users_coll.insert_one(user_doc)
    return {"status": "success", "message": "User created successfully"}

@app.post("/api/auth/login")
async def login(email: str = Form(...), password: str = Form(...)):
    user = users_coll.find_one({"email": email})
    if not user or not pwd_context.verify(password, user["password"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    
    token = create_access_token(data={"sub": user["email"], "role": user["role"]})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"],
        "name": user.get("name", "User")
    }

@app.post("/api/auth/google")
async def google_auth(credential: str = Form(...)):
    try:
        # Verify the Google ID token
        idinfo = id_token.verify_oauth2_token(credential, google_requests.Request(), GOOGLE_CLIENT_ID)
        
        email = idinfo['email']
        name = idinfo.get('name', email.split('@')[0])
        
        user = users_coll.find_one({"email": email})
        if not user:
            # Create new user if doesn't exist
            user_doc = {
                "email": email,
                "name": name,
                "role": "user", # Google sign-ins are users by default
                "google_id": idinfo['sub'],
                "created_at": now_iso()
            }
            users_coll.insert_one(user_doc)
            user = user_doc

        token = create_access_token(data={"sub": email, "role": user["role"]})
        return {
            "access_token": token,
            "token_type": "bearer",
            "role": user["role"],
            "name": name
        }
    except ValueError:
        # Invalid token
        raise HTTPException(status_code=401, detail="Invalid Google token")


@app.get("/")
def home():
    """Redirect root to the frontend site if available, else return API status."""
    if SITE_DIR.is_dir():
        return RedirectResponse(url="/site/index.html")
    return {
        "status": "API is running",
        "model_loaded": model_state["loaded"],
        "storage_root": str(RESULTS_DIR),
        "endpoints": ["/save-audio", "/generate-report", "/download-zip"],
    }


@app.post("/save-audio")
async def save_audio(
    question_number: int = Form(...),
    session_id: Optional[str] = Form(None),
    audio: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
) -> dict:
    print(f"\n[DEBUG] API HIT: /save-audio (Question {question_number})")
    question_number = validate_question_number(question_number)
    safe_session_id = normalize_session_id(session_id)
    upload = audio or file
    if upload is None:
        raise HTTPException(status_code=400, detail="Upload an audio file using form field 'audio' or 'file'.")

    root = session_dir(safe_session_id)
    ensure_session_dirs(root)
    require_prior_transcripts(root, question_number)

    recording_path = root / "recordings" / f"q{question_number}.wav"
    with recording_path.open("wb") as buffer:
        shutil.copyfileobj(upload.file, buffer)

    try:
        transcript = audio_to_text(str(recording_path))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc

    transcript_path = question_transcript_path(root, question_number)
    write_text(transcript_path, transcript.strip() + "\n")

    combined_path = build_combined_transcript(root, question_number)
    metadata = save_metadata(root, safe_session_id, combined_used=combined_path.name)

    return {
        "status": "success",
        "session_id": safe_session_id,
        "question_number": question_number,
        "recording": f"recordings/q{question_number}.wav",
        "transcript": f"transcripts/q{question_number}.txt",
        "combined_transcript": f"transcripts/{combined_path.name}",
        "metadata": metadata,
    }


@app.post("/generate-report")
async def generate_report(
    question_number: int = Form(...),
    session_id: str = Form(...),
) -> dict:
    print(f"\n[DEBUG] API HIT: /generate-report (Session {session_id})")
    ensure_model_loaded()
    question_number = validate_question_number(question_number)
    safe_session_id = normalize_session_id(session_id)
    root = session_dir(safe_session_id)
    ensure_session_dirs(root)

    combined_path = build_combined_transcript(root, question_number)
    combined_text = read_text(combined_path)

    try:
        prediction = predict_text(
            combined_text,
            model_state["model"],
            model_state["features"],
            model_state["threshold"],
            model_state["margin"],
            model_state["scaler"],
            filename=combined_path.name,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}") from exc

    payload = report_payload(safe_session_id, question_number, combined_path.name, combined_text, prediction)
    report_path = root / "results" / f"report_q{question_number}.json"
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    save_metadata(root, safe_session_id, combined_used=combined_path.name)
    zip_path = zip_session_folder(root, safe_session_id)
    
    # --- Google Drive Upload Logic ---
    print(f"DEBUG: Attempting to upload ZIP for session {safe_session_id} to Drive...")
    upload_result = upload_zip_to_drive(zip_path, folder_name=f"session_{safe_session_id}")
    
    if upload_result:
        drive_link = upload_result.get("download_link")
        print(f"SUCCESS: Uploaded to Drive: {upload_result.get('file_id')}")
    else:
        drive_link = None
        print("ERROR: Drive upload failed (check terminal for API errors).")

    metadata = save_metadata(root, safe_session_id, combined_used=combined_path.name, drive_link=drive_link)

    # --- Save to MongoDB ---
    try:
        transcript_doc = {
            "session_id": safe_session_id,
            "question_number": question_number,
            "transcript": combined_text,
            "can_be_used": True,  # Default to True
            "created_at": now_iso(),
            "prediction_result": {
                "prediction": payload["label_str"],
                "probability": payload["prob_schiz"],
                "report": payload["report"],
                "biomarkers": payload["biomarkers"],
                "triggered": payload["triggered"]
            }
        }
        # Update if exists for this session, else insert (overwrites previous step's transcript with latest)
        transcripts_coll.update_one(
            {"session_id": safe_session_id},
            {"$set": transcript_doc},
            upsert=True
        )
        print(f"SUCCESS: Full transcript (Q1-{question_number}) saved to MongoDB for session {safe_session_id}")
    except Exception as mongo_exc:
        print(f"ERROR: Failed to save to MongoDB: {mongo_exc}")

    if AUTO_DELETE_AFTER_UPLOAD and drive_link:
        shutil.rmtree(root, ignore_errors=True)

    return {
        "status": "success",
        "session_id": safe_session_id,
        "question_number": question_number,
        "report_file": f"results/report_q{question_number}.json",
        "zip_file": zip_path.name,
        "download_link": drive_link,
        "drive_file_id": upload_result.get("file_id") if upload_result else None,
        "local_zip_available": zip_path.exists(),
        "metadata": metadata,
        "prediction": payload["label_str"],
        "probability": payload["prob_schiz"],
        "report": payload["report"],
        "biomarkers": payload["biomarkers"],
        "triggered": payload["triggered"],
    }


@app.get("/download-zip", response_model=None)
def download_zip(session_id: str) -> dict | FileResponse:
    safe_session_id = normalize_session_id(session_id)
    root = session_dir(safe_session_id)
    zip_path = session_zip_path(root, safe_session_id)
    metadata = load_metadata(root, safe_session_id)

    drive_link = metadata.get("drive_download_link")
    if drive_link:
        return {
            "status": "success",
            "session_id": safe_session_id,
            "download_link": drive_link,
        }

    if zip_path.exists():
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=zip_path.name,
        )

    if root.exists():
        zip_path = zip_session_folder(root, safe_session_id)
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=zip_path.name,
        )

    raise HTTPException(status_code=404, detail="Session not found.")


@app.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    participant_id: str = Form("anonymous_participant"),
) -> dict:
    print("\n[DEBUG] API HIT: /analyze")
    saved = await save_audio(question_number=1, session_id=participant_id, file=file)
    form_report = await generate_report(question_number=1, session_id=saved["session_id"])
    return form_report


# --- Dashboard Endpoints ---

@app.get("/api/transcripts")
async def get_all_transcripts(user: dict = Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        docs = list(transcripts_coll.find().sort("created_at", -1))
        for doc in docs:
            doc["_id"] = str(doc["_id"])
        return docs
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch transcripts: {exc}")


@app.post("/api/transcripts/{t_id}/status")
async def update_transcript_status(t_id: str, can_be_used: bool = Form(...), user: dict = Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        res = transcripts_coll.update_one(
            {"_id": ObjectId(t_id)},
            {"$set": {"can_be_used": can_be_used}}
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Transcript not found")
        return {"status": "success", "can_be_used": can_be_used}
    except Exception as exc:
        if isinstance(exc, HTTPException): raise exc
        raise HTTPException(status_code=500, detail=f"Update failed: {exc}")





@app.post("/api/transcripts/{t_id}/analyze")
async def analyze_stored_transcript(t_id: str, user: dict = Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        t = transcripts_coll.find_one({"_id": ObjectId(t_id)})
        if not t:
            raise HTTPException(status_code=404, detail="Transcript not found")
        
        result = predict_text(
            text=t["transcript"],
            model=model_state["model"],
            feature_names=model_state["features"],
            threshold=model_state["threshold"],
            margin=model_state["margin"],
            scaler=model_state["scaler"],
            filename=f"{t['session_id']}_reanalysis.txt"
        )
        
        # Update the stored prediction with full details
        transcripts_coll.update_one(
            {"_id": ObjectId(t_id)},
            {"$set": {"prediction_result": {
                "prediction": result["label_str"],
                "probability": result["prob_schiz"],
                "report": result["report"],
                "biomarkers": result["biomarkers"],
                "triggered": result["triggered"]
            }}}
        )
        
        return {
            "prediction": result["label_str"],
            "probability": result["prob_schiz"],
            "report": result["report"],
            "biomarkers": result["biomarkers"],
            "triggered": result["triggered"]
        }
    except Exception as exc:
        print(f"Analysis error: {exc}")
        raise HTTPException(status_code=500, detail=f"Re-analysis failed: {exc}")


@app.delete("/api/transcripts/{t_id}")
async def delete_transcript(t_id: str, user: dict = Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        res = transcripts_coll.delete_one({"_id": ObjectId(t_id)})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Transcript not found")
        return {"status": "success"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/sync-results")
async def sync_results_to_db(user: dict = Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    synced_count = 0
    errors = []
    
    if not RESULTS_DIR.exists():
        print(f"DEBUG SYNC: Results directory {RESULTS_DIR} does not exist.")
        return {"status": "success", "synced": 0, "message": "Results directory not found"}

    print(f"DEBUG SYNC: Scanning {RESULTS_DIR}...")
    for item in RESULTS_DIR.iterdir():
        if not item.is_dir():
            continue
            
        session_id = item.name
        if session_id.startswith("session_"):
            session_id = session_id.replace("session_", "")
            
        print(f"DEBUG SYNC: Found session folder {item.name}")
        # Format 1: session_ID/transcripts/combined_upto_qX.txt
        transcripts_dir = item / "transcripts"
        if transcripts_dir.exists():
            # Find the highest q number
            q_nums = []
            for f in transcripts_dir.glob("combined_upto_q*.txt"):
                match = re.search(r"q(\d+)\.txt$", f.name)
                if match:
                    q_nums.append(int(match.group(1)))
            
            if q_nums:
                max_q = max(q_nums)
                transcript_path = transcripts_dir / f"combined_upto_q{max_q}.txt"
                report_path = item / "results" / f"report_q{max_q}.json"
                
                print(f"DEBUG SYNC: Syncing session {session_id} from {transcript_path.name}")
                try:
                    transcript_text = transcript_path.read_text(encoding="utf-8")
                    prediction_result = None
                    
                    if report_path.exists():
                        report_data = json.loads(report_path.read_text(encoding="utf-8"))
                        prediction_result = {
                            "prediction": report_data.get("prediction"),
                            "probability": report_data.get("probability"),
                            "report": report_data.get("report"),
                            "biomarkers": report_data.get("biomarkers", []),
                            "triggered": report_data.get("triggered", [])
                        }
                    
                    transcript_doc = {
                        "session_id": session_id,
                        "question_number": max_q,
                        "transcript": transcript_text,
                        "can_be_used": True,
                        "created_at": datetime.fromtimestamp(transcript_path.stat().st_mtime, timezone.utc).isoformat(),
                        "prediction_result": prediction_result
                    }
                    
                    transcripts_coll.update_one(
                        {"session_id": session_id},
                        {"$set": transcript_doc},
                        upsert=True
                    )
                    synced_count += 1
                except Exception as e:
                    print(f"DEBUG SYNC ERROR: {session_id}: {e}")
                    errors.append(f"Error syncing {session_id}: {e}")
        else:
            # Format 2: ID/YYYYMMDD_HHMMSS_transcript.txt (old format)
            print(f"DEBUG SYNC: No transcripts directory in {item.name}. Checking for old format files...")
            for f in item.glob("*_transcript.txt"):
                try:
                    transcript_text = f.read_text(encoding="utf-8")
                    timestamp_str = f.name.split("_")[0] + "_" + f.name.split("_")[1]
                    report_path = item / f"{timestamp_str}_report.txt" # some might be .txt
                    
                    prediction_result = None
                    if report_path.exists():
                        # Simple parse if it's the old .txt report format
                        report_text = report_path.read_text(encoding="utf-8")
                        pred = "UNKNOWN"
                        if "SCHIZOPHRENIA" in report_text.upper(): pred = "SCHIZOPHRENIA"
                        elif "CONTROL" in report_text.upper(): pred = "CONTROL"
                        prediction_result = {"prediction": pred, "report": report_text}
                    
                    transcript_doc = {
                        "session_id": session_id,
                        "question_number": 1,
                        "transcript": transcript_text,
                        "can_be_used": True,
                        "created_at": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(),
                        "prediction_result": prediction_result
                    }
                    
                    transcripts_coll.update_one(
                        {"session_id": f"{session_id}_{timestamp_str}"},
                        {"$set": transcript_doc},
                        upsert=True
                    )
                    synced_count += 1
                except Exception as e:
                    errors.append(f"Error syncing {f.name}: {e}")

    return {
        "status": "success",
        "synced": synced_count,
        "errors": errors if errors else None
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
