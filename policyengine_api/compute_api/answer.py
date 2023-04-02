from policyengine_api.data import database
import openai
from openai.embeddings_utils import get_embedding, cosine_similarity
import pandas as pd
import json
import requests
import time
from pathlib import Path


folder = Path(__file__).parent

if not (folder / "parameter_embeddings.csv.gz").exists():
    response = requests.get(
        "https://api.github.com/repos/PolicyEngine/policyengine-api/releases/assets/101996330",
        headers={
            "Accept": "application/octet-stream",
        },
    )

    response.raise_for_status()

    with open(folder / "parameter_embeddings.csv.gz", "wb") as f:
        f.write(response.content)

embeddings_df = pd.read_csv(
    folder / "parameter_embeddings.csv.gz", compression="gzip"
)
embeddings_df.parameter_embedding = embeddings_df.parameter_embedding.apply(
    lambda x: eval(x)
)


def embed(prompt, engine="text-embedding-ada-002"):
    return get_embedding(prompt, engine=engine)


def write_prompt(question, relevant_parameters):
    prompt = f"""Question: {question}
    Here's some metadata about the parameters that are relevant to your question:
    Relevant parameters: {relevant_parameters}

    Task: Convert the question into a reform of the syntax below. If not specified, assume the reform starts on 2023-01-01 and ends on 2024-01-01.
    

    Reform syntax you should write in: {{ "parameter_name": {{ "start_date.end_date": value }} }}
    e.g. "basic rate at 25%" -> {{ "hmrc.income_tax.rates.uk[0].rate": {{ "2023-01-01.2024-01-01": 0.25 }} }}
    Reply only with valid JSON.
    """

    return prompt


def get_gpt4_response(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
    )["choices"][0]["message"]["content"]
    return response


def get_policy_id(reform, country_id):
    payload = {"data": reform}
    url = f"https://api.policyengine.org/{country_id}/policy"

    response = requests.post(url, json=payload)

    # json.result.policy_id

    return response.json()["result"]["policy_id"]


def get_policyengine_impact(policy_id, country_id):

    # Next step: run the reform on the PolicyEngine API

    url = f"https://api.policyengine.org/uk/economy/{policy_id}/over/1?time_period=2023&region={country_id}"

    response = requests.get(url).json()

    # if 'status' = 'computing', wait 5 seconds and try again until 'status' = 'ok'

    while response["status"] == "computing":
        time.sleep(3)
        response = requests.get(url).json()

    impact = response["result"]

    return impact


def trigger_answer(question_id: str):
    # Get the question and country_id

    row = database.query(
        "SELECT * FROM question WHERE question_id = ?",
        (question_id,),
    ).fetchone()
    if row is None:
        return dict(
            status="error",
            message=f"Question {question_id} not found",
        )
    row_dict = dict(row)
    country_id = row_dict["country_id"]
    question = row_dict["question"]

    # Get the policy ID

    embedding = embed(question)
    embeddings_df["similarities"] = embeddings_df[
        embeddings_df.country_id == country_id
    ].parameter_embedding.apply(lambda x: cosine_similarity(x, embedding))

    top5 = (
        embeddings_df.sort_values("similarities", ascending=False)
        .head(5)["json"]
        .values
    )

    reform_generation_prompt = write_prompt(question, top5)

    # Update the subtask status to "parse_policy"

    database.query(
        "UPDATE question SET subtask = ? WHERE question_id = ?",
        ("parse_policy", question_id),
    )

    # Get the reform

    reform = json.loads(get_gpt4_response(reform_generation_prompt))

    policy_id = get_policy_id(reform, country_id)

    # Update the subtask status to "run_policy"

    database.query(
        "UPDATE question SET subtask = ?, policy_id = ? WHERE question_id = ?",
        ("run_policy", policy_id, question_id),
    )

    impact = get_policyengine_impact(policy_id, country_id)

    question_answer_prompt = f"""Relevant economic impact simulation data: {impact}
        Question: {question}
        Task: Write a concise single-sentence response to the question, using only the impact data. If you can't from the data, say it.
        Give financial amounts in short-form (e.g. £1bn, 250m, etc.). This is the {country_id.upper()} context, so use the appropriate currency and English style.
    """

    # Update the subtask status to "answer_question"

    database.query(
        "UPDATE question SET subtask = ? WHERE question_id = ?",
        ("answer_question", question_id),
    )

    answer = get_gpt4_response(question_answer_prompt)

    # Update the subtask status to "complete" and the answer

    database.query(
        "UPDATE question SET subtask = ?, status = ?, answer = ? WHERE question_id = ?",
        ("complete", "ok", answer, question_id),
    )
