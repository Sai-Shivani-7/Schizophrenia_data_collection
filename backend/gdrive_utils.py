import os
import pickle
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR = Path(__file__).resolve().parent

# OAuth Configuration
SCOPES = ["https://www.googleapis.com/auth/drive"]
CLIENT_SECRETS_FILE = BASE_DIR / "oauth_client.json"
TOKEN_FILE = BASE_DIR / "token.pickle"

# Drive Folder Configuration
PARENT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "1c-J-Ok5WMR7J1VdCoiMBM4_dzZVx_7p8")

def get_gdrive_service():
    """
    Authenticates using OAuth 2.0 (User Credentials).
    Will open a browser window for the first-time login.
    Saves the session in token.pickle for future use.
    """
    creds = None
    
    # Load existing token if available
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)

    # If there are no valid credentials, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing Google Drive credentials...")
            creds.refresh(Request())
        else:
            if not CLIENT_SECRETS_FILE.exists():
                print(f"ERROR: '{CLIENT_SECRETS_FILE.name}' not found in {BASE_DIR}")
                print("Please download your OAuth client JSON from Google Cloud Console.")
                return None
            
            print("Starting Google Drive OAuth flow... Please check your browser.")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
            # Use port=0 to find any available port
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)

    return build("drive", "v3", credentials=creds)


def make_file_public(service, file_id: str) -> None:
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
        fields="id",
    ).execute()


def upload_zip_to_drive(zip_path: str | Path, folder_name: Optional[str] = None) -> Optional[dict]:
    """
    Upload a session ZIP to the user's Google Drive.
    """
    service = get_gdrive_service()
    if not service:
        return None

    zip_path = Path(zip_path)
    if not zip_path.exists():
        print(f"Upload skipped: ZIP not found at {zip_path}")
        return None

    name = f"{folder_name}.zip" if folder_name else zip_path.name

    try:
        media = MediaFileUpload(
            str(zip_path),
            mimetype="application/zip",
            resumable=True,
            chunksize=1024 * 1024,
        )

        print(f"---> UPLOADING: '{name}' to Google Drive folder ID: {PARENT_FOLDER_ID}")
        
        request = service.files().create(
            body={"name": name, "parents": [PARENT_FOLDER_ID]},
            media_body=media,
            fields="id, webViewLink, parents",
            supportsAllDrives=True,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"Uploading... {int(status.progress() * 100)}%")

        file_id = response["id"]
        
        # We try to make it public, but it's not strictly required for the upload to succeed
        try:
            make_file_public(service, file_id)
        except Exception:
            pass

        print(f"DONE: File is saved in Drive folder: {PARENT_FOLDER_ID}")
        print(f"Link: {response.get('webViewLink')}")

        return {
            "file_id": file_id,
            "download_link": f"https://drive.google.com/uc?export=download&id={file_id}",
            "web_view_link": response.get("webViewLink"),
        }
    except Exception as exc:
        print(f"Google Drive upload error: {exc}")
        return None
