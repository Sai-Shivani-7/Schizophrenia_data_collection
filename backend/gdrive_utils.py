import os
import io
import zipfile
import tempfile
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# The ID of the folder you provided
PARENT_FOLDER_ID = "1c-J-Ok5WMR7J1VdCoiMBM4_dzZVx_7p8"

# Path to your service account credentials file
CREDENTIALS_FILE = "service_account.json"

def get_gdrive_service():
    if not os.path.exists(CREDENTIALS_FILE):
        return None
    
    try:
        creds = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE, 
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Error initializing GDrive service: {e}")
        return None

def upload_zip_to_drive(participant_id, files_dict):
    """
    Zips the audio, transcript, and report, then uploads the single ZIP to Drive.
    Handling duplicate IDs by appending a unique timestamp.
    files_dict: { 'display_name.wav': 'local/path/to/file.wav', ... }
    """
    service = get_gdrive_service()
    if not service:
        print("WARNING: GDrive service account credentials (service_account.json) not found. Skipping cloud upload.")
        return None

    # 1. Create unique ZIP name
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{participant_id}_session_{ts}.zip"
    
    # 2. Create the ZIP file in a temporary location
    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for arcname, local_path in files_dict.items():
                if os.path.exists(local_path):
                    zf.write(local_path, arcname)
                else:
                    print(f"Warning: File {local_path} not found for zipping.")

        # 3. Resumable Upload (Safe for large files)
        media = MediaFileUpload(
            zip_path,
            mimetype="application/zip",
            resumable=True,
            chunksize=1024 * 1024 # 1MB chunks
        )

        request = service.files().create(
            body={'name': zip_name, 'parents': [PARENT_FOLDER_ID]},
            media_body=media,
            fields='id'
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"Uploading ZIP {zip_name}: {int(status.progress() * 100)}%")

        print(f"SUCCESS: Uploaded {zip_name} to Google Drive (ID: {response.get('id')})")
        return response.get('id')

    except Exception as e:
        print(f"GDrive ZIP Upload Error: {e}")
        return None
    finally:
        # Cleanup temporary zip
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except:
                pass
