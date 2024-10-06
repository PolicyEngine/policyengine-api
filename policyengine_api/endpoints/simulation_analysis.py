from policyengine_api.data import local_database
from policyengine_api.utils import hash_object
from flask import request, Response
from rq import Queue
from redis import Redis
from typing import Optional
from policyengine_api.utils.ai_analysis import trigger_ai_analysis

queue = Queue(connection=Redis())

# Add an optional param to get_analysis that is the prompt, with a default value of None
# If the prompt is passed as an arg, treat that as the prompt, else if it's within the request args, use that, else it's equal to None



def execute_simulation_analysis(country_id: str) -> Response:
    
    # Pop the various parameters from the request
    payload = request.json

    currency_code = payload.get("currency_code")
    selected_version = payload.get("selected_version")
    time_period = payload.get("time_period")
    impact = payload.get("impact")
    policy_label = payload.get("policy_label")
    policy = payload.get("policy")
    region = payload.get("region")
    param_baseline_values = payload.get("param_baseline_values")
    params = payload.get("params")
    audience = payload.get("audience")

    # Check if the region is enhanced_cps 
    is_enhanced_cps = "enhanced_cps" in region

    # Add data to the prompt


    # If a calculated record exists for this prompt, return it as a
    # streaming response - util function


    # Otherwise, pass prompt to Claude, then return streaming function


# def get_simulation_analysis(country_id: str, prompt_id = None, prompt: Optional[str] = None):
#     if prompt is None:
#         try:
#             prompt = flask.request.json.get("prompt")
#         except:
#             prompt = None
# 
#     if prompt:
#         existing_analysis = local_database.query(
#             f"SELECT analysis FROM analysis WHERE prompt = ? LIMIT 1",
#             (prompt,),
#         ).fetchone()
#         if not existing_analysis:
#             local_database.query(
#                 f"INSERT INTO analysis (prompt_id, prompt, analysis, status) VALUES (?, ?, ?, ?)",
#                 (None, prompt, "", "computing"),
#             )
#         else:
#             # Update status to computing and analysis to empty string
#             local_database.query(
#                 f"UPDATE analysis SET status = ?, analysis = ? WHERE prompt = ?",
#                 ("computing", "", prompt),
#             )
#         prompt_id = local_database.query(
#             f"SELECT prompt_id FROM analysis WHERE prompt = ? LIMIT 1",
#             (prompt,),
#         ).fetchone()["prompt_id"]
#         queue.enqueue(
#             # Ensure we have enough memory to run this
#             trigger_ai_analysis,
#             prompt,
#             prompt_id,
#             job_id=str(prompt_id),
#             ttl=600,
#         )
#         return dict(
#             status="computing",
#             message="Analysis is being computed.",
#             result=dict(prompt_id=prompt_id),
#         )
#     else:
#         analysis_row = local_database.query(
#             "SELECT analysis, status FROM analysis WHERE prompt_id = ?",
#             (prompt_id,),
#         ).fetchone()
#         analysis = analysis_row["analysis"]
#         status = analysis_row["status"]
#         return dict(
#             result=dict(
#                 prompt_id=prompt_id,
#                 analysis=analysis,
#             ),
#             status=status,
#         )
# 