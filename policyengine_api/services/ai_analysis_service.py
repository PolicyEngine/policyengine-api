import anthropic
import os
import json
import time
from typing import Generator
from policyengine_api.data import local_database


class AIAnalysisService:
    """
    Base class for various AI analysis-based services,
    including SimulationAnalysisService, that connects with the analysis
    local database table
    """

    def get_existing_analysis(
        self, prompt: str
    ) -> Generator[str, None, None] | None:
        """
        Get existing analysis from the local database
        """

        analysis = local_database.query(
            f"SELECT analysis FROM analysis WHERE prompt = ?",
            (prompt,),
        ).fetchone()

        if analysis is None:
            return None

        def generate():

            # First, yield prompt so it's accessible on front end
            initial_data = {
                "stream": "",
                "prompt": prompt,
            }
            yield json.dumps(initial_data) + "\n"

            chunk_size = 5
            for i in range(0, len(analysis["analysis"]), chunk_size):
                chunk = analysis["analysis"][i : i + chunk_size]
                yield json.dumps({"stream": chunk}) + "\n"
                time.sleep(0.05)

        return generate()

    def trigger_ai_analysis(self, prompt: str) -> Generator[str, None, None]:

        # Configure a Claude client
        claude_client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )

        def generate():
            chunk_size = 5
            response_text = ""
            buffer = ""

            # First, yield prompt so it's accessible on front end
            initial_data = {
                "stream": "",
                "prompt": prompt,
            }

            yield json.dumps(initial_data) + "\n"

            with claude_client.messages.stream(
                model="claude-3-5-sonnet-20240620",
                max_tokens=1500,
                temperature=0.0,
                system="Respond with a historical quote",
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for item in stream.text_stream:
                    buffer += item
                    response_text += item
                    while len(buffer) >= chunk_size:
                        chunk = buffer[:chunk_size]
                        buffer = buffer[chunk_size:]
                        yield json.dumps({"stream": chunk}) + "\n"

            if buffer:
                yield json.dumps({"stream": buffer}) + "\n"

            # Finally, update the analysis record and return
            local_database.query(
                f"INSERT INTO analysis (prompt, analysis, status) VALUES (?, ?, ?)",
                (prompt, response_text, "ok"),
            )

        return generate()
