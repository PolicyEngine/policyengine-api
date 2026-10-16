"""Streamlit experiment that answers a UK policy question with GPT-4 and the API.

It finds related parameters by embedding similarity, asks GPT-4 to write the
reform as JSON, runs it on the public PolicyEngine API, and asks GPT-4 to answer
from the resulting economic impact.
"""

import ast
import json
import os
import time

import openai
import pandas as pd
import requests
import streamlit as st
from openai.embeddings_utils import cosine_similarity, get_embedding

# Point OpenAI to the API key
openai.api_key = os.environ["OPENAI_API_KEY"]


@st.cache_data
def get_embeddings_df() -> pd.DataFrame:
    """Load parameter_embeddings.csv.gz, parsing each embedding string to a list."""
    embeddings_df = pd.read_csv("parameter_embeddings.csv.gz", compression="gzip")
    embeddings_df.parameter_embedding = embeddings_df.parameter_embedding.apply(
        ast.literal_eval
    )
    return embeddings_df


@st.cache_data
def embed(prompt: str, engine: str = "text-embedding-ada-002") -> list[float]:
    """Return the OpenAI embedding of ``prompt``, cached across Streamlit reruns."""
    return get_embedding(prompt, engine=engine)


embeddings_df = get_embeddings_df().copy()

st.title("GPT-4 PolicyEngine analysis")

# Text box for people to write "change the basic rate of income tax to 20%", single line

question = st.text_input(
    "Enter a policy question",
    "Revenue impact of changing the basic rate of income tax to 25%",
)

# First task: convert the question to a reform that maps each parameter path to
# its values by period, for example hmrc.income_tax.rates.uk[0].rate set to 0.25
# for the period 2023-01-01.2024-01-01.

# We're going to do this with GPT4- we'll pass in the question, the related parameter
# metadata, and the task description.

# First, get related parameters via a search through GPT-embedded parameters.


# columns are name, json, parameter_embedding

# Get the top 5 most similar parameters

embedding = embed(question)
embeddings_df["similarities"] = embeddings_df.parameter_embedding.apply(
    lambda x: cosine_similarity(x, embedding)
)

top5 = embeddings_df.sort_values("similarities", ascending=False).head(5)["json"].values  # noqa: PD011  # a string column, which pandas 3 stores in an extension array that .to_numpy() would convert
# display in streamlit


def write_prompt(question: str, relevant_parameters: object) -> str:
    """Build the GPT-4 prompt that rewrites ``question`` as a reform JSON object."""
    return f"""Question: {question}
    Here's some metadata about the parameters that are relevant to your question:
    Relevant parameters: {relevant_parameters}

    Task: Convert the question into a reform of the syntax below. If not specified, assume the reform starts on 2023-01-01 and ends on 2024-01-01.


    Reform syntax you should write in: {{ "parameter_name": {{ "start_date.end_date": value }} }}
    e.g. "basic rate at 25%" -> {{ "hmrc.income_tax.rates.uk[0].rate": {{ "2023-01-01.2024-01-01": 0.25 }} }}
    Reply only with valid JSON.
    """  # noqa: E501  # the prompt is sent to GPT-4 verbatim; wrapping would change it


reform_generation_prompt = write_prompt(question, top5)

# Now, pass the prompt to GPT-4


@st.cache_data
def get_gpt4_response(prompt: str) -> str:
    """Return GPT-4's reply to ``prompt`` as one user message, cached across reruns."""
    return openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
    )["choices"][0]["message"]["content"]


response = get_gpt4_response(reform_generation_prompt)

reform = json.loads(response)

# Next step: register the reform on the PolicyEngine API


@st.cache_data
def get_policyengine_impact(reform: object) -> object:
    """Create ``reform`` on the public UK API and return its 2023 UK economic impact.

    Poll every five seconds, with no time limit, while the impact is computing.
    """
    payload = {"data": reform}
    url = "https://api.policyengine.org/uk/policy"

    response = requests.post(url, json=payload)  # noqa: S113  # a timeout would change this experiment's behaviour; it waits as long as the API takes

    # json.result.policy_id

    policy_id = response.json()["result"]["policy_id"]

    # Next step: run the reform on the PolicyEngine API

    url = f"https://api.policyengine.org/uk/economy/{policy_id}/over/1?time_period=2023&region=uk"

    response = requests.get(url).json()  # noqa: S113  # a timeout would change this experiment's behaviour; it waits as long as the API takes

    # if 'status' = 'computing', wait 5 seconds and try again until 'status' = 'ok'

    while response["status"] == "computing":
        time.sleep(5)
        response = requests.get(url).json()  # noqa: S113  # a timeout would change this experiment's behaviour; it waits as long as the API takes

    return response["result"]


# Now, get GPT4 to answer the question with the impact JSON.

impact = get_policyengine_impact(reform)

question_answer_prompt = f"""Relevant economic impact simulation data: {impact}

    Question: {question}

    Task: Write a concise single-sentence response to the question, using only the impact data. If you can't from the data, say it.

    Give financial amounts in short-form (e.g. £1bn, 250m, etc.).
"""  # noqa: E501  # the prompt is sent to GPT-4 verbatim; wrapping would change it

answer = get_gpt4_response(question_answer_prompt)

st.write(answer)

st.write("## How I worked it out")

with st.expander("My prompt for understanding your reform"):
    st.write(reform_generation_prompt)

with st.expander("What I thought your reform was"):
    st.write(reform)

with st.expander("My prompt for answering your question"):
    st.write(question_answer_prompt)
