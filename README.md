# MP42srt

Takes your mp4 file and creates .srt subtitles with Google Cloud's Speech-to-Text.

## Requirements
- ffmpeg installed and in $PATH
- uv (https://docs.astral.sh/uv/) - like pip but better
- Google Cloud project with a Google Cloud Storage bucket, and a service account that has correct permissions. Example roles:
  - `Cloud Speech Administrator` - gives access to required speech recognition APIs
  - `Storage Object User` - gives access to Google Cloud Storage in the project

## Quickstart
1. Add service account credentials to root folder of code, rename file to `credentials.json`.
2. `uv venv`
3. `source .venv/bin/activate`
4. `uv pip install -e .`
5. `python main.py --help`

## Examples

### Default - English
`python main.py --gcs-bucket-name 'mp42srt' speech.mp4`

### Specific language
`python main.py --gcs-bucket-name 'mp42srt' --lang 'fi-FI' puhe.mp4`
