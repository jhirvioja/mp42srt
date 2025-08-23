import typer
import tempfile
import uuid
from pathlib import Path
from typing import Optional
from typing_extensions import Annotated
from google.oauth2 import service_account
from google.api_core import exceptions as google_exceptions
from halo import Halo

from audio_processor import extract_audio, upload_audio_to_gcs
from transcriber import transcribe_audio
from srt_generator import generate_srt_file


def main(
    mp4_file: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            writable=False,
            readable=True,
            resolve_path=True,
            help="Path to the input MP4 video file.",
        ),
    ],
    gcs_bucket_name: Annotated[
        str,
        typer.Option(
            "--gcs-bucket-name",
            help="Google Cloud Storage bucket name for temporary audio storage.",
        ),
    ],
    output_srt: Annotated[
        Optional[Path],
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Path to save the output SRT file. Defaults to the same name as the video file.",
        ),
    ] = None,
    language_code: Annotated[
        str,
        typer.Option(
            "--lang",
            "-l",
            help="Language code for speech recognition (e.g., 'en-US', 'fi-FI').",
        ),
    ] = "en-US",
    credentials_file: Annotated[
        Path,
        typer.Option(
            "--credentials",
            "-c",
            help="Path to the Google Cloud service account JSON file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ] = Path("credentials.json"),
):
    """
    Extracts audio from an MP4 file, transcribes it using Google Speech-to-Text,
    and creates a SubRip (SRT) subtitle file.
    """
    print(f"mp42srt processing file: {mp4_file.name}")

    if output_srt is None:
        output_srt = mp4_file.with_suffix(".srt")

    counter = 0
    original_stem = output_srt.stem
    while output_srt.exists():
        new_filename = f"{original_stem}-{counter}{output_srt.suffix}"
        output_srt = output_srt.with_name(new_filename)
        counter += 1

    try:
        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_file)
        )
    except Exception as e:
        print(f"❌ Error loading credentials from {credentials_file}.")
        print(f"   Please ensure it's a valid service account JSON file. Details: {e}")
        raise typer.Exit(code=1)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_wav_path = Path(temp_dir) / "audio.wav"
        gcs_uri = None

        try:
            extract_audio(mp4_file, temp_wav_path)
            remote_blob_name = f"audio-transcripts/{uuid.uuid4()}.wav"
            gcs_uri = upload_audio_to_gcs(
                temp_wav_path, gcs_bucket_name, remote_blob_name, credentials
            )
            response = transcribe_audio(gcs_uri, language_code, credentials)
            generate_srt_file(response, output_srt)

        except Exception as e:
            print(f"❌ An error occurred: {e}")
            raise typer.Exit(code=1)
        finally:
            spinner_cleanup = Halo(
                text=f"🧹 Cleaning up: Deleting {gcs_uri} from bucket...",
                spinner="dots",
            )
            spinner_cleanup.start()
            if gcs_uri:
                try:
                    from google.cloud import storage

                    storage_client = storage.Client(credentials=credentials)
                    bucket = storage_client.bucket(gcs_bucket_name)
                    remote_blob_name = "/".join(gcs_uri.split("/")[3:])
                    blob = bucket.blob(remote_blob_name)
                    blob.delete()
                    spinner_cleanup.succeed(
                        "Cleanup complete, deleted blob from GCS bucket."
                    )
                except google_exceptions.NotFound:
                    spinner_cleanup.succeed(
                        "File already deleted or was not uploaded successfully."
                    )
                except Exception as e:
                    spinner_cleanup.warn(
                        f"Warning: Failed to delete blob from GCS. Manual cleanup may be required. Error: {e}"
                    )
            else:
                spinner_cleanup.succeed("No GCS file to clean up.")


if __name__ == "__main__":
    typer.run(main)
