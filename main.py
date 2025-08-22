import typer
import ffmpeg
import tempfile
import uuid
from halo import Halo
from google.cloud import speech, storage
from google.oauth2 import service_account
from google.api_core import exceptions as google_exceptions
from pathlib import Path
from typing_extensions import Annotated


def format_timestamp(seconds: float) -> str:
    """
    Converts a time in seconds to the SRT timestamp format (HH:MM:SS,ms).

    Args:
        seconds: The time in seconds.

    Returns:
        A string representing the time in SRT format.
    """
    assert seconds >= 0, "non-negative timestamp expected"
    milliseconds = round(seconds * 1000.0)

    hours = milliseconds // 3_600_000
    milliseconds %= 3_600_000

    minutes = milliseconds // 60_000
    milliseconds %= 60_000

    seconds = milliseconds // 1_000
    milliseconds %= 1_000

    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def main(
        mp4_file: Annotated[Path, typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            writable=False,
            readable=True,
            resolve_path=True,
            help="Path to the input MP4 video file."
        )],
        gcs_bucket_name: Annotated[str, typer.Option(
            "--gcs-bucket-name",
            help="Google Cloud Storage bucket name for temporary audio storage.",
        )],
        output_srt: Annotated[Path, typer.Option(
            "--output", "-o",
            help="Path to save the output SRT file. Defaults to the same name as the video file."
        )] = None,
        language_code: Annotated[str, typer.Option(
            "--lang", "-l",
            help="Language code for speech recognition (e.g., 'en-US', 'fi-FI')."
        )] = "en-US",
        credentials_file: Annotated[Path, typer.Option(
            "--credentials", "-c",
            help="Path to the Google Cloud service account JSON file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        )] = Path("credentials.json"),
):
    """
    Extracts audio from an MP4 file, transcribes it using Google Speech-to-Text,
    and creates a SubRip (SRT) subtitle file.

    Requires a Google Cloud service account JSON file for authentication.
    """

    print(f"Processing file: {mp4_file.name}")

    if output_srt is None:
        output_srt = mp4_file.with_suffix(".srt")

    counter = 0
    original_stem = output_srt.stem
    while output_srt.exists():
        new_filename = f"{original_stem}-{counter}{output_srt.suffix}"
        output_srt = output_srt.with_name(new_filename)
        counter += 1

    try:
        credentials = service_account.Credentials.from_service_account_file(str(credentials_file))
    except Exception as e:
        print(f"❌ Error loading credentials from {credentials_file}.")
        print(f"   Please ensure it's a valid service account JSON file. Details: {e}")
        raise typer.Exit(code=1)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_wav_path = Path(temp_dir) / "audio.wav"

        spinner_ffmpeg = Halo(text="Step 1/4: Extracting audio from video...", spinner='dots')
        try:
            spinner_ffmpeg.start()
            (
                ffmpeg
                .input(str(mp4_file))
                .output(str(temp_wav_path), acodec='pcm_s16le', ac=1, ar='16000')
                .run(quiet=True, overwrite_output=True)
            )
            spinner_ffmpeg.succeed("Audio extracted successfully.")
        except ffmpeg.Error as e:
            spinner_ffmpeg.fail("Error extracting audio with ffmpeg.")
            print(e.stderr.decode())
            raise typer.Exit(code=1)

        spinner_gcs = Halo(text=f"Step 2/4: Uploading audio to GCS bucket '{gcs_bucket_name}'...", spinner='dots')
        storage_client = storage.Client(credentials=credentials)
        bucket = storage_client.bucket(gcs_bucket_name)

        remote_blob_name = f"audio-transcripts/{uuid.uuid4()}.wav"
        blob = bucket.blob(remote_blob_name)

        try:
            spinner_gcs.start()
            blob.upload_from_filename(str(temp_wav_path))
            gcs_uri = f"gs://{gcs_bucket_name}/{remote_blob_name}"
            spinner_gcs.succeed(f"Audio uploaded to {gcs_uri}")
        except Exception as e:
            spinner_gcs.fail("An error occurred during GCS upload.")
            print(f"Details: {e}")
            raise typer.Exit(code=1)

        spinner_transcribe = Halo(text='Step 3/4: Transcribing audio (this may take a while)...', spinner='dots')
        try:
            speech_client = speech.SpeechClient(credentials=credentials)
            audio = speech.RecognitionAudio(uri=gcs_uri)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code=language_code,
                enable_word_time_offsets=True,
                enable_automatic_punctuation=True,
            )

            request = speech.LongRunningRecognizeRequest(config=config, audio=audio)

            spinner_transcribe.start()
            operation = speech_client.long_running_recognize(request=request)
            response = operation.result(timeout=900)
            spinner_transcribe.succeed('Transcription complete.')

        except Exception as e:
            spinner_transcribe.fail('An error occurred during transcription.')
            print(f"Details: {e}")
            raise typer.Exit(code=1)
        finally:
            spinner_cleanup = Halo(text=f"🧹 Cleaning up: Deleting {gcs_uri} from bucket...", spinner='dots')
            spinner_cleanup.start()
            try:
                blob.delete()
                spinner_cleanup.succeed("Cleanup complete.")
            except google_exceptions.NotFound:
                spinner_cleanup.succeed("File already deleted or was not uploaded successfully.")
            except Exception as e:
                spinner_cleanup.warn(
                    f"Warning: Failed to delete blob from GCS. Manual cleanup may be required. Error: {e}")

        spinner_srt = Halo(text="Step 4/4: Generating SRT subtitle file...", spinner='dots')
        try:
            spinner_srt.start()
            srt_content = []
            subtitle_index = 1
            max_chars_per_line = 42
            max_line_duration = 3.5
            max_lines_per_subtitle = 2

            for result in response.results:
                if not result.alternatives[0].words:
                    continue

                words = result.alternatives[0].words
                current_subtitle_words = []
                current_subtitle_start_time = None

                # Iterate through words to build subtitle blocks
                for word_info in words:
                    word = word_info.word.strip()

                    # Set the start time for the first word in the subtitle
                    if not current_subtitle_words:
                        current_subtitle_start_time = word_info.start_time.total_seconds()

                    # Check if adding the new word would break the rules
                    temp_line = " ".join([w['word'] for w in current_subtitle_words] + [word])
                    temp_lines = temp_line.split('\n')

                    # Logic to check for splits
                    should_split = False
                    if len(temp_lines) > max_lines_per_subtitle:
                        should_split = True
                    elif len(temp_line) > max_chars_per_line and len(temp_lines) > 1:
                        should_split = True
                    elif (word_info.end_time.total_seconds() - current_subtitle_start_time) > max_line_duration:
                        should_split = True
                    elif word.endswith(('.', '?', '!')):
                        should_split = True

                    # If a split is needed, save the current subtitle and start a new one
                    if should_split and current_subtitle_words:
                        end_time = current_subtitle_words[-1]['end_time'].total_seconds()
                        transcript_line = " ".join([w['word'] for w in current_subtitle_words])

                        srt_content.append(str(subtitle_index))
                        srt_content.append(
                            f"{format_timestamp(current_subtitle_start_time)} --> {format_timestamp(end_time)}")
                        srt_content.append(transcript_line.strip())
                        srt_content.append("")
                        subtitle_index += 1

                        current_subtitle_words = [{'word': word, 'end_time': word_info.end_time}]
                        current_subtitle_start_time = word_info.start_time.total_seconds()

                    else:
                        # Append the word to the current line
                        current_subtitle_words.append({'word': word, 'end_time': word_info.end_time})

                # Append any remaining words as the final subtitle
                if current_subtitle_words:
                    end_time = current_subtitle_words[-1]['end_time'].total_seconds()
                    transcript_line = " ".join([w['word'] for w in current_subtitle_words])

                    srt_content.append(str(subtitle_index))
                    srt_content.append(
                        f"{format_timestamp(current_subtitle_start_time)} --> {format_timestamp(end_time)}")
                    srt_content.append(transcript_line.strip())
                    srt_content.append("")

            with open(str(output_srt), "w", encoding="utf-8") as f:
                f.write("\n".join(srt_content))

            spinner_srt.succeed(f"SRT file saved to: {output_srt}")
            print("🎉 Success!")
        except Exception as e:
            spinner_srt.fail("An error occurred during SRT file generation.")
            print(f"Details: {e}")
            raise typer.Exit(code=1)


if __name__ == "__main__":
    typer.run(main)
