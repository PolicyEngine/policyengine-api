import os
from policyengine_api.country import validate_country
from policyengine_api.data import local_database
from policyengine_api.utils import hash_object
import time
import flask
from rq import Queue
from redis import Redis
import datetime
import requests
import anthropic

queue = Queue(connection=Redis())

WRITE_ANALYSIS_EVERY_N_SECONDS = 5


def trigger_policy_analysis(prompt: str, prompt_id: int):
    """
    Trigger AI-based analysis via Claude; streaming documentation
    available at https://docs.anthropic.com/claude/reference/messages-streaming
    """

    # Configure a Claude client
    claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    try:
        # Create a server-sent event manager, which will stream
        # messages via a returned iterator
        message = claude_client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=1500,
            temperature=0.0,
            stream=True,
            system="Respond with a historical quote",
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise e

    # Instantiate an empty string for analysis text and track time
    analysis_text = ""
    last_update_time = time.time()

    # For each item from the SSE message manager...
    # Note that this doesn't handle all possible messages, such as
    # content_block_start and message_end; for all event types,
    # view the documentation in the func's docstring
    for item in message:
        # Handle potential errors
        if item.type == "error":
            raise Exception(
                f"Error within Claude API integration: {item.error.message}"
            )
        # If the manager returns a textual change...
        elif item.type == "content_block_delta":
            # Append the new content to the full block
            new_content = item.delta.text
            analysis_text += new_content

            # If we haven't updated for a while, then fire UPDATE
            if time.time() - last_update_time > WRITE_ANALYSIS_EVERY_N_SECONDS:
                last_update_time = time.time()
                local_database.query(
                    f"UPDATE analysis SET analysis = ?  WHERE prompt_id = ?",
                    (analysis_text, prompt_id),
                )

    # Finally, update the analysis record and return
    local_database.query(
        f"UPDATE analysis SET analysis = ?  WHERE prompt_id = ?",
        (analysis_text, prompt_id),
    )
    local_database.query(
        f"UPDATE analysis SET status = ?  WHERE prompt_id = ?",
        ("ok", prompt_id),
    )

    return analysis_text


def get_analysis(country_id: str, prompt_id=None):
    invalid_country = validate_country(country_id)
    if invalid_country:
        return invalid_country
    try:
        prompt = flask.request.json.get("prompt")
    except:
        prompt = None
    if prompt:
        existing_analysis = local_database.query(
            f"SELECT analysis FROM analysis WHERE prompt = ? LIMIT 1",
            (prompt,),
        ).fetchone()
        if not existing_analysis:
            local_database.query(
                f"INSERT INTO analysis (prompt_id, prompt, analysis, status) VALUES (?, ?, ?, ?)",
                (None, prompt, "", "computing"),
            )
        else:
            # Update status to computing and analysis to empty string
            local_database.query(
                f"UPDATE analysis SET status = ?, analysis = ? WHERE prompt = ?",
                ("computing", "", prompt),
            )
        prompt_id = local_database.query(
            f"SELECT prompt_id FROM analysis WHERE prompt = ? LIMIT 1",
            (prompt,),
        ).fetchone()["prompt_id"]
        queue.enqueue(
            # Ensure we have enough memory to run this
            trigger_policy_analysis,
            prompt,
            prompt_id,
            job_id=str(prompt_id),
            ttl=600,
        )
        return dict(
            status="computing",
            message="Analysis is being computed.",
            result=dict(prompt_id=prompt_id),
        )
    else:
        analysis_row = local_database.query(
            "SELECT analysis, status FROM analysis WHERE prompt_id = ?",
            (prompt_id,),
        ).fetchone()
        analysis = analysis_row["analysis"]
        status = analysis_row["status"]
        return dict(
            result=dict(
                prompt_id=prompt_id,
                analysis=analysis,
            ),
            status=status,
        )
