import ffmpeg
from halo import Halo
from google.cloud import storage
from pathlib import Path


def extract_audio(input_file: Path, output_file: Path):
    """Extracts audio from a video file using ffmpeg."""
    spinner = Halo(text="Step 1/4: Extracting audio from video...", spinner="dots")
    try:
        spinner.start()
        (
            ffmpeg.input(str(input_file))
            .output(str(output_file), acodec="pcm_s16le", ac=1, ar="16000")
            .run(quiet=True, overwrite_output=True)
        )
        spinner.succeed("Audio extracted successfully.")
    except ffmpeg.Error as e:
        spinner.fail("Error extracting audio with ffmpeg.")
        raise RuntimeError(f"FFmpeg error: {e.stderr.decode()}")


def upload_audio_to_gcs(
    local_path: Path, bucket_name: str, remote_blob_name: str, credentials
):
    """Uploads a local audio file to a Google Cloud Storage bucket."""
    spinner = Halo(
        text=f"Step 2/4: Uploading audio to GCS bucket '{bucket_name}'...",
        spinner="dots",
    )
    storage_client = storage.Client(credentials=credentials)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(remote_blob_name)
    try:
        spinner.start()
        blob.upload_from_filename(str(local_path))
        gcs_uri = f"gs://{bucket_name}/{remote_blob_name}"
        spinner.succeed(f"Audio uploaded to {gcs_uri}")
        return gcs_uri
    except Exception as e:
        spinner.fail("An error occurred during GCS upload.")
        raise RuntimeError(f"GCS upload error: {e}")
