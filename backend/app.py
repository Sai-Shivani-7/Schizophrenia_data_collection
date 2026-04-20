import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import joblib
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from gdrive_utils import upload_zip_to_drive
from utils import audio_to_text, predict_text


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


def build_combined_transcript(root: Path, question_number: int) -> Path:
    require_prior_transcripts(root, question_number)

    parts = []
    missing_current = []
    for i in range(1, question_number + 1):
        path = question_transcript_path(root, i)
        if not path.exists():
            missing_current.append(f"q{i}.txt")
            continue
        text = read_text(path).strip()
        parts.append(f"Q{i}:\n{text}\n")

    if missing_current:
        raise HTTPException(
            status_code=400,
            detail=f"Missing transcript(s): {', '.join(missing_current)}.",
        )

    combined_path = combined_transcript_path(root, question_number)
    write_text(combined_path, "\n".join(parts).strip() + "\n")
    return combined_path


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
        "prediction": payload["prediction"],
        "probability": payload["probability"],
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
