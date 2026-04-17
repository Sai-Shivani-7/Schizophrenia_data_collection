from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
import joblib
import os
import shutil
import asyncio
from datetime import datetime
from utils import audio_to_text, predict_text
from gdrive_utils import upload_zip_to_drive

app = FastAPI(title="Schizophrenia Speech Analysis API")

# Enable CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
MODEL_PATH = "schizo_speech_model.pkl"
RESULTS_DIR = "results"

# Ensure results directory exists
os.makedirs(RESULTS_DIR, exist_ok=True)

# Global state for model components
model_state = {
    "model": None,
    "threshold": None,
    "margin": None,
    "features": None,
    "scaler": None,
    "loaded": False
}

@app.on_event("startup")
def load_model():
    global model_state
    target_path = MODEL_PATH
    if not os.path.exists(target_path):
        fallback = os.path.join("..", MODEL_PATH)
        if os.path.exists(fallback):
            target_path = fallback
        
    if os.path.exists(target_path):
        try:
            ckpt = joblib.load(target_path)
            model_state["model"] = ckpt["model"]
            model_state["threshold"] = ckpt["threshold"]
            model_state["margin"] = ckpt["margin"]
            model_state["features"] = ckpt["features"]
            model_state["scaler"] = ckpt["scaler"]
            model_state["loaded"] = True
            print(f"SUCCESS: Model checkpoint loaded successfully from {target_path}")
        except Exception as e:
            print(f"ERROR: Error loading model checkpoint: {e}")
    else:
        print(f"WARNING: Model file not found at {MODEL_PATH}")

@app.get("/")
def home():
    return {
        "status": "API is running", 
        "model_loaded": model_state["loaded"]
    }

@app.post("/analyze")
async def analyze(
    file: UploadFile = File(...), 
    participant_id: str = Form("anonymous_participant")
):
    if not model_state["loaded"]:
        raise HTTPException(status_code=500, detail="Model checkpoint not loaded on server.")
    
    # Create structured storage folder
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_path = os.path.join(RESULTS_DIR, participant_id)
    os.makedirs(folder_path, exist_ok=True)

    # Save permanent audio path
    audio_filename = f"{timestamp}_audio.wav"
    audio_path = os.path.join(folder_path, audio_filename)
    
    with open(audio_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # 1. Speech to Text conversion using Whisper
        print(f"[{participant_id}] Transcribing: {file.filename}")
        text = audio_to_text(audio_path)
        
        # 2. Complete Prediction Pipeline
        result = predict_text(
            text,
            model_state["model"],
            model_state["features"],
            model_state["threshold"],
            model_state["margin"],
            model_state["scaler"],
            filename=file.filename
        )

        # 3. Save Transcript and Report as persistent files
        transcript_filename = f"{timestamp}_transcript.txt"
        report_filename = f"{timestamp}_report.txt"
        transcript_path = os.path.join(folder_path, transcript_filename)
        report_path = os.path.join(folder_path, report_filename)

        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(text)
        
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(result["report"])

        # 4. Sync as a single ZIP to Google Drive (Background Task)
        files_to_zip = {
            "session_audio.wav": audio_path,
            "session_transcript.txt": transcript_path,
            "clinical_report.txt": report_path
        }
        
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, upload_zip_to_drive, participant_id, files_to_zip)

        # 5. Return structured results
        return {
            "transcription": text,
            "prediction": result["label_str"],
            "probability": result["prob_schiz"],
            "report": result["report"],
            "biomarkers": result["biomarkers"],
            "triggered": result.get("triggered", []),
            "threshold": result.get("threshold", 0.45),
            "storage_path": folder_path,
            "cloud_sync": "ZIP upload initiated"
        }

    except Exception as e:
        print(f"Error during analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
