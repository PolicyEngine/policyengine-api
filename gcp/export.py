import os
from pathlib import Path

GAE = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
# If it's a filepath, read the file. Otherwise, it'll be JSON
try:
    Path(GAE).resolve(strict=True)
    with open(GAE, "r") as f:
        GAE = f.read()
except Exception as e:
    pass
DB_PD = os.environ["POLICYENGINE_DB_PASSWORD"]
GITHUB_MICRODATA_TOKEN = os.environ["POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# Export GAE to to .gac.json and DB_PD to .dbpw in the current directory

with open(".gac.json", "w") as f:
    f.write(GAE)

with open(".dbpw", "w") as f:
    f.write(DB_PD)

# in gcp/compute_api/Dockerfile, replace .github_microdata_token with the contents of the file
for dockerfile_location in [
    "gcp/policyengine_api/Dockerfile",
]:
    with open(dockerfile_location, "r") as f:
        dockerfile = f.read()
        dockerfile = dockerfile.replace(
            ".github_microdata_token", GITHUB_MICRODATA_TOKEN
        )
        dockerfile = dockerfile.replace(".openai_api_key", OPENAI_API_KEY)

    with open(dockerfile_location, "w") as f:
        f.write(dockerfile)
