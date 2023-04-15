import requests
import pandas as pd
import json
from tqdm import tqdm
import numpy as np
from pathlib import Path
import h5py
from pathlib import Path
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
folder = Path(__file__).parent

COUNTRIES = ["uk", "us"]


def get_embedding(text):
    # Use Huggingface model to get embeddings
    return model.encode(text)


metadata_df = pd.DataFrame()

for country_id in COUNTRIES:
    metadata = (
        requests.get(f"https://api.policyengine.org/{country_id}/metadata")
        .json()
        .get("result")
    )
    variable_metadata = pd.DataFrame(
        dict(
            name=list(metadata["variables"].keys()),
            text=[
                (metadata["variables"][name].get("name") or "")
                + " "
                + (metadata["variables"][name].get("label") or "")
                + " "
                + (metadata["variables"][name].get("description") or "")
                for name in metadata["variables"]
            ],
        )
    )
    variable_metadata["type"] = "variable"

    parameter_metadata = pd.DataFrame(
        dict(
            name=list(metadata["parameters"].keys()),
            text=[
                (metadata["parameters"][name].get("parameter") or "")
                + " "
                + (metadata["parameters"][name].get("label") or "")
                + " "
                + (metadata["parameters"][name].get("documentation") or "")
                for name in metadata["parameters"]
            ],
        )
    )
    parameter_metadata["type"] = "parameter"
    parameter_metadata = parameter_metadata[
        np.array(
            [
                metadata["parameters"][name]["type"] == "parameter"
                for name in metadata["parameters"]
            ]
        )
    ]

    metadata = pd.concat([variable_metadata, parameter_metadata])
    metadata["country_id"] = country_id
    metadata_df = pd.concat([metadata_df, metadata])

embeddings = {}

for i, row in tqdm(
    metadata_df.iterrows(), total=len(metadata_df), desc="Creating embeddings"
):
    try:
        embeddings[row["name"]] = np.array(get_embedding(row["text"]))
    except KeyboardInterrupt as e:
        raise e
    except Exception as e:
        print(f"Failed to create embedding for {row['name']}")

# Add embeddings to an 'embeddings' column in the metadata

metadata_df["embedding"] = metadata_df["name"].apply(
    lambda name: embeddings.get(name)
)
embedding_dimensions = metadata_df["embedding"].values[0].shape[0]
embeddings = np.array(metadata_df["embedding"].values.tolist()).reshape(
    -1, embedding_dimensions
)
metadata_df[["name", "country_id", "type"]].to_csv(
    "metadata.csv.gz", index=False, compression="gzip"
)

with h5py.File("embeddings.h5", "w") as f:
    f.create_dataset("embeddings", data=embeddings)
