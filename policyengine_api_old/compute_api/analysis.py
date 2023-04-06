import openai
import os
from policyengine_api.data import database
from policyengine_api.utils import hash_object
import time

openai.api_key = os.getenv("OPENAI_API_KEY")

WRITE_ANALYSIS_EVERY_N_SECONDS = 5


def trigger_policy_analysis(prompt_id: int):
    prompt = database.query(
        "SELECT prompt FROM analysis WHERE prompt_id = ?", (prompt_id,)
    ).fetchone()[0]
    analysis_text = ""
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    analysis_text = ""
    last_update_time = time.time()

    for response in response:
        new_content = (
            response.get("choices", [{}])[0]
            .get("delta", {})
            .get("content", "")
        )
        if not new_content:
            continue
        analysis_text += new_content
        if time.time() - last_update_time > WRITE_ANALYSIS_EVERY_N_SECONDS:
            last_update_time = time.time()
            database.query(
                f"UPDATE analysis SET analysis = ?  WHERE prompt_id = ?",
                (analysis_text, prompt_id),
            )
    database.query(
        f"UPDATE analysis SET analysis = ?  WHERE prompt_id = ?",
        (analysis_text, prompt_id),
    )
    database.query(
        f"UPDATE analysis SET status = ?  WHERE prompt_id = ?",
        ("ok", prompt_id),
    )

    return analysis_text
