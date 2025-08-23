from halo import Halo
from pathlib import Path
from utils import format_timestamp


def generate_srt_file(response, output_path: Path):
    """Generates an SRT subtitle file from a Google Speech-to-Text response."""
    spinner = Halo(text="Step 4/4: Generating SRT subtitle file...", spinner="dots")
    try:
        spinner.start()
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
            current_subtitle_start_time = 0.0

            # Iterate through words to build subtitle blocks
            for word_info in words:
                word = word_info.word.strip()

                # Set the start time for the first word in the subtitle
                if not current_subtitle_words:
                    current_subtitle_start_time = word_info.start_time.total_seconds()

                # Check if adding the new word would break the rules
                temp_line = " ".join([w.word for w in current_subtitle_words] + [word])
                temp_lines = temp_line.split("\n")

                # Logic to check for splits
                should_split = False
                if len(temp_lines) > max_lines_per_subtitle:
                    should_split = True
                elif len(temp_line) > max_chars_per_line and len(temp_lines) > 1:
                    should_split = True
                elif (
                    word_info.end_time.total_seconds() - current_subtitle_start_time
                ) > max_line_duration:
                    should_split = True
                elif word.endswith((".", "?", "!")):
                    should_split = True

                # If a split is needed, save the current subtitle and start a new one
                if should_split and current_subtitle_words:
                    end_time = current_subtitle_words[-1].end_time.total_seconds()
                    transcript_line = " ".join([w.word for w in current_subtitle_words])

                    srt_content.append(str(subtitle_index))
                    srt_content.append(
                        f"{format_timestamp(current_subtitle_start_time)} --> {format_timestamp(end_time)}"
                    )
                    srt_content.append(transcript_line.strip())
                    srt_content.append("")
                    subtitle_index += 1

                    current_subtitle_words = [word_info]
                    current_subtitle_start_time = word_info.start_time.total_seconds()
                else:
                    # Append the word to the current line
                    current_subtitle_words.append(word_info)

            # Append any remaining words as the final subtitle
            if current_subtitle_words:
                end_time = current_subtitle_words[-1].end_time.total_seconds()
                transcript_line = " ".join([w.word for w in current_subtitle_words])
                srt_content.append(str(subtitle_index))
                srt_content.append(
                    f"{format_timestamp(current_subtitle_start_time)} --> {format_timestamp(end_time)}"
                )
                srt_content.append(transcript_line.strip())
                srt_content.append("")

        with open(str(output_path), "w", encoding="utf-8") as f:
            f.write("\n".join(srt_content))

        spinner.succeed(f"SRT file saved to: {output_path}")

    except Exception as e:
        spinner.fail("An error occurred during SRT file generation.")
        raise RuntimeError(f"SRT generation error: {e}")
