import openai
import os
from policyengine_api.data import local_database
from policyengine_api.utils import hash_object
import time
import flask
from rq import Queue
from redis import Redis
import datetime
import requests

queue = Queue(connection=Redis())

openai.api_key = os.getenv("OPENAI_API_KEY")

WRITE_ANALYSIS_EVERY_N_SECONDS = 5


def trigger_policy_analysis(prompt: str, prompt_id: int):
    analysis_text = ""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
    except Exception as e:
        raise e
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
            local_database.query(
                f"UPDATE analysis SET analysis = ?  WHERE prompt_id = ?",
                (analysis_text, prompt_id),
            )
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
        ).fetchone()[0]
        queue.enqueue(
            trigger_policy_analysis, prompt, prompt_id, job_id=str(prompt_id)
        )
        return dict(
            status="computing",
            message="Analysis is being computed.",
            result=dict(prompt_id=prompt_id),
        )
    else:
        analysis = local_database.query(
            "SELECT analysis FROM analysis WHERE prompt_id = ?", prompt_id
        ).fetchone()[0]
        status = local_database.query(
            "SELECT status FROM analysis WHERE prompt_id = ?", prompt_id
        ).fetchone()[0]
        return dict(
            result=dict(
                prompt_id=prompt_id,
                analysis=analysis,
            ),
            status=status,
        )
