import anthropic
import os
import time
from policyengine_api.data import local_database
from typing import Generator


def trigger_ai_analysis(prompt: str) -> Generator[str, None, None]:
    
    # Configure a Claude client
    claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def generate():
        chunk_size = 5
        response_text = ""
        buffer = ""

        with claude_client.messages.stream(
            model="claude-3-5-sonnet-20240620",
            max_tokens=1500,
            temperature=0.0,
            system="Respond with a historical quote",
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for item in stream.text_stream:
                buffer += item
                while len(buffer) >= chunk_size:
                    yield buffer[:chunk_size]
                    buffer = buffer[chunk_size:]
        
        if buffer:
            yield buffer

        # Finally, update the analysis record and return
        local_database.query(
            f"INSERT INTO analysis (prompt, analysis, status) VALUES (?, ?, ?)",
            (prompt, response_text, "ok"),
        )

    return generate()


def get_existing_analysis(prompt: str) -> Generator[str, None, None] | None:
    """
    Get existing analysis from the local database
    """

    analysis = local_database.query(
        f"SELECT analysis FROM analysis WHERE prompt = ?",
        (prompt,),
    ).fetchone()

    if analysis is None:
        return None
    
    def analysis_generator():

        chunk_size = 5
        for i in range(0, len(analysis["analysis"]), chunk_size):
            yield analysis["analysis"][i:i + chunk_size]
            time.sleep(0.05)

    return analysis_generator()