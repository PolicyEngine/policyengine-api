import pandas as pd
import numpy as np
from pathlib import Path
import h5py
import flask
from sentence_transformers import SentenceTransformer
import requests

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
folder = Path(".")

COUNTRIES = ["uk"]


def get_embedding(text):
    # Use Huggingface model to get embeddings
    return model.encode(text)


if False and not (folder / "embeddings.h5").exists():
    EMBEDDINGS_URL = "https://api.github.com/repos/PolicyEngine/policyengine-api/releases/assets/103041096"
    EMBEDDINGS_PATH = folder / "embeddings.h5"
    EMBEDDINGS_PATH.write_bytes(
        requests.get(
            EMBEDDINGS_URL, headers={"Accept": "application/octet-stream"}
        ).content
    )

if False and not (folder / "metadata.csv.gz").exists():
    METADATA_URL = "https://api.github.com/repos/PolicyEngine/policyengine-api/releases/assets/103041106"
    METADATA_PATH = folder / "metadata.csv.gz"
    METADATA_PATH.write_bytes(
        requests.get(
            METADATA_URL, headers={"Accept": "application/octet-stream"}
        ).content
    )

metadata_df = pd.read_csv(folder / "metadata.csv.gz", compression="gzip")
folder = Path(".")

metadata_df[["name", "country_id", "type"]].to_csv(
    "metadata.csv.gz", index=False, compression="gzip"
)

with h5py.File("embeddings.h5", "r") as f:
    embeddings = f["embeddings"][:]

metadata_df["embedding"] = embeddings.tolist()

embedding_dimensions = len(embeddings[0])

# Use FAISS to create an index

import faiss

index_names = [
    "uk_parameters",
    "uk_variables",
    "us_parameters",
    "us_variables",
]

indexes = {
    name: faiss.IndexFlatL2(embedding_dimensions) for name in index_names
}

names = {name: [] for name in index_names}

for metadata_type in ["parameter", "variable"]:
    for country_id in COUNTRIES:
        name = f"{country_id}_{metadata_type}s"
        index = indexes[name]
        metadata = metadata_df[
            (metadata_df["type"] == metadata_type)
            * (metadata_df["country_id"] == country_id)
        ]
        embeddings = np.array(metadata["embedding"].tolist()).reshape(
            -1, embedding_dimensions
        )
        index.add(embeddings)
        names[name] = metadata["name"].tolist()


def get_search(country_id: str, k=10):
    type = flask.request.args.get("type", "parameter")
    query = flask.request.args.get("query").lower()
    if type not in ["parameter", "variable"]:
        raise ValueError("Type must be parameter or variable")
    if country_id not in COUNTRIES:
        raise ValueError(f"Country ID must be one of {COUNTRIES}")
    index_name = f"{country_id}_{type}s"
    embedding = get_embedding(query)
    index = indexes[index_name]
    _, indices = index.search(np.array([embedding]), k)
    return {
        "result": [names[index_name][i] for i in indices[0]],
        "status": "ok",
    }
