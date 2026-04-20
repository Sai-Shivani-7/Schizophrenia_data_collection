import os
from pathlib import Path
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


BASE_DIR = Path(__file__).resolve().parent

# Override these with environment variables when deploying.
PARENT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "1c-J-Ok5WMR7J1VdCoiMBM4_dzZVx_7p8")
CREDENTIALS_FILE = Path(os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", BASE_DIR / "service_account.json"))


def get_gdrive_service():
    if not CREDENTIALS_FILE.exists():
        print(f"WARNING: Google service account file not found at {CREDENTIALS_FILE}. Skipping Drive upload.")
        return None

    try:
        creds = service_account.Credentials.from_service_account_file(
            str(CREDENTIALS_FILE),
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        return build("drive", "v3", credentials=creds)
    except Exception as exc:
        print(f"Error initializing Google Drive service: {exc}")
        return None


def make_file_public(service, file_id: str) -> None:
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
        fields="id",
    ).execute()


def upload_zip_to_drive(zip_path: str | Path, folder_name: Optional[str] = None) -> Optional[dict]:
    """
    Upload an already-created session ZIP to the configured Google Drive folder.

    Returns:
        {
          "file_id": "...",
          "download_link": "https://drive.google.com/uc?export=download&id=...",
          "web_view_link": "https://drive.google.com/file/d/.../view?usp=drivesdk"
        }
    """
    service = get_gdrive_service()
    if not service:
        return None

    zip_path = Path(zip_path)
    if not zip_path.exists():
        print(f"Google Drive upload skipped because ZIP does not exist: {zip_path}")
        return None

    name = zip_path.name
    if folder_name:
        name = f"{folder_name}.zip"

    try:
        media = MediaFileUpload(
            str(zip_path),
            mimetype="application/zip",
            resumable=True,
            chunksize=1024 * 1024,
        )

        request = service.files().create(
            body={"name": name, "parents": [PARENT_FOLDER_ID]},
            media_body=media,
            fields="id, webViewLink",
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"Uploading ZIP {name}: {int(status.progress() * 100)}%")

        file_id = response["id"]
        try:
            make_file_public(service, file_id)
        except Exception as exc:
            print(f"WARNING: Uploaded ZIP, but could not make it public: {exc}")

        return {
            "file_id": file_id,
            "download_link": f"https://drive.google.com/uc?export=download&id={file_id}",
            "web_view_link": response.get("webViewLink"),
        }
    except Exception as exc:
        print(f"Google Drive ZIP upload error: {exc}")
        return None
