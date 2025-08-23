from google.cloud import speech
from google.oauth2.service_account import Credentials
from halo import Halo


def transcribe_audio(gcs_uri: str, language_code: str, credentials: Credentials):
    """Transcribes an audio file from GCS using the Speech-to-Text API."""
    spinner = Halo(
        text="Step 3/4: Transcribing audio (this may take a while)...", spinner="dots"
    )
    try:
        speech_client = speech.SpeechClient(credentials=credentials)  # type: ignore
        audio = speech.RecognitionAudio(uri=gcs_uri)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code=language_code,
            enable_word_time_offsets=True,
            enable_automatic_punctuation=True,
        )
        request = speech.LongRunningRecognizeRequest(config=config, audio=audio)

        spinner.start()
        operation = speech_client.long_running_recognize(request=request)
        response = operation.result(timeout=900)
        spinner.succeed("Transcription complete.")
        return response
    except Exception as e:
        spinner.fail("An error occurred during transcription.")
        raise RuntimeError(f"Transcription error: {e}")
