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

# Export GAE to to .gac.json and DB_PD to .dbpw in the current directory

with open(".gac.json", "w") as f:
    f.write(GAE)

with open(".dbpw", "w") as f:
    f.write(DB_PD)

with open(".github_microdata_token", "w") as f:
    f.write(GITHUB_MICRODATA_TOKEN)
