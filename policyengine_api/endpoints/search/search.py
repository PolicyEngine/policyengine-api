from flask import Response

# import pandas as pd
# import numpy as np
import json

# from pathlib import Path
# import h5py
import flask

# from sentence_transformers import SentenceTransformer
# import requests

# model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
# folder = Path(".")

# COUNTRIES = ["uk"]


# def get_embedding(text):
#     # Use Huggingface model to get embeddings
#     return model.encode(text)


# if not (folder / "embeddings.h5").exists():
#     EMBEDDINGS_URL = "https://api.github.com/repos/PolicyEngine/policyengine-api/releases/assets/103041096"
#     EMBEDDINGS_PATH = folder / "embeddings.h5"
#     EMBEDDINGS_PATH.write_bytes(
#         requests.get(
#             EMBEDDINGS_URL, headers={"Accept": "application/octet-stream"}
#         ).content
#     )

# if not (folder / "metadata.csv.gz").exists():
#     METADATA_URL = "https://api.github.com/repos/PolicyEngine/policyengine-api/releases/assets/103041106"
#     METADATA_PATH = folder / "metadata.csv.gz"
#     METADATA_PATH.write_bytes(
#         requests.get(
#             METADATA_URL, headers={"Accept": "application/octet-stream"}
#         ).content
#     )

# metadata_df = pd.read_csv(folder / "metadata.csv.gz", compression="gzip")
# folder = Path(".")

# metadata_df[["name", "country_id", "type"]].to_csv(
#     "metadata.csv.gz", index=False, compression="gzip"
# )

# with h5py.File("embeddings.h5", "r") as f:
#     embeddings = f["embeddings"][:]

# metadata_df["embedding"] = embeddings.tolist()

# embedding_dimensions = len(embeddings[0])

# # Use FAISS to create an index

# import faiss

# index_names = [
#     "uk_parameters",
#     "uk_variables",
#     "us_parameters",
#     "us_variables",
# ]

# indexes = {
#     name: faiss.IndexFlatL2(embedding_dimensions) for name in index_names
# }

# names = {name: [] for name in index_names}

# for metadata_type in ["parameter", "variable"]:
#     for country_id in COUNTRIES:
#         name = f"{country_id}_{metadata_type}s"
#         index = indexes[name]
#         metadata = metadata_df[
#             (metadata_df["type"] == metadata_type)
#             * (metadata_df["country_id"] == country_id)
#         ]
#         embeddings = np.array(metadata["embedding"].tolist()).reshape(
#             -1, embedding_dimensions
#         )
#         index.add(embeddings)
#         names[name] = metadata["name"].tolist()


def get_search():
    """
    get_search (Removed)
    ---
    This endpoint has been removed and is no longer functional.

    Description:
        This endpoint previously searched using hugging face embeddings and torch.
        It has been removed due to infrequent usage and performance considerations.

    HTTP Method:
        GET

    URL:
        /country_id/search

    Response:
        - Status Code: 410 Gone
        - Content: JSON object with "error" message

    Example:
        {
            "status": "error",
            "message": "This endpoint has been removed"
        }

    ---------------------------------------------------
    Below is the previous implementation:

    type = flask.request.args.get("type", "parameter")
    query = flask.request.args.get("query").lower()
    results_param = flask.request.args.get("results")

    def get_search(country_id, max_results=10):
        invalid_country = validate_country(country_id)
        if invalid_country:
            return invalid_country

        if type not in ["parameter", "variable"]:
            body = {
                "status": "error",
                "message": "Type must be 'parameter' or 'variable'.",
            }
            return Response(json.dumps(body), status=400)

        if results_param is not None:
            try:
                max_results = int(results_param)
                if max_results <= 0:
                    raise ValueError
                max_results = min(max_results, 50)  # Limit maximum results to 50
            except ValueError:
                body = {
                    "status": "error",
                    "message": "Invalid value for results. Must be a positive integer.",
                }
                return Response(json.dumps(body), status=400)

        index_name = f"{country_id}_{type}s"
        embedding = get_embedding(query)
        index = indexes[index_name]
        _, indices = index.search(np.array([embedding]), max_results)

        results = [names[index_name][i] for i in indices[0]]

        if not results:
            body = {"status": "error", "message": "No results found for the query"}
            return Response(json.dumps(body), status=404)

        body = {
            "status": "ok",
            "result": results,
        }
        return Response(json.dumps(body), status=200)

    """

    body = {"status": "error", "message": "This endpoint has been removed"}
    return Response(json.dumps(body), status=410)
