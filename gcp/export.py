import os

DB_PD = os.environ["POLICYENGINE_DB_PASSWORD"]
GITHUB_MICRODATA_TOKEN = os.environ["POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
HUGGING_FACE_TOKEN = os.environ["HUGGING_FACE_TOKEN"]
SIMULATION_ENTRYPOINT_URL = os.environ["SIMULATION_ENTRYPOINT_URL"]
OLD_SIMULATION_GATEWAY_URL = os.environ["OLD_SIMULATION_GATEWAY_URL"]
SIM_ENTRYPOINT = os.environ["SIM_ENTRYPOINT"]
GATEWAY_AUTH_ISSUER = os.environ["GATEWAY_AUTH_ISSUER"]
GATEWAY_AUTH_AUDIENCE = os.environ["GATEWAY_AUTH_AUDIENCE"]
GATEWAY_AUTH_CLIENT_ID = os.environ["GATEWAY_AUTH_CLIENT_ID"]
GATEWAY_AUTH_CLIENT_SECRET_RESOURCE = os.environ["GATEWAY_AUTH_CLIENT_SECRET_RESOURCE"]

# Export DB_PD to .dbpw in the current directory

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
        dockerfile = dockerfile.replace(".anthropic_api_key", ANTHROPIC_API_KEY)
        dockerfile = dockerfile.replace(".openai_api_key", OPENAI_API_KEY)
        dockerfile = dockerfile.replace(".hugging_face_token", HUGGING_FACE_TOKEN)
        dockerfile = dockerfile.replace(
            ".simulation_entrypoint_url", SIMULATION_ENTRYPOINT_URL
        )
        dockerfile = dockerfile.replace(
            ".old_simulation_gateway_url", OLD_SIMULATION_GATEWAY_URL
        )
        dockerfile = dockerfile.replace(".sim_entrypoint", SIM_ENTRYPOINT)
        dockerfile = dockerfile.replace(".gateway_auth_issuer", GATEWAY_AUTH_ISSUER)
        dockerfile = dockerfile.replace(".gateway_auth_audience", GATEWAY_AUTH_AUDIENCE)
        dockerfile = dockerfile.replace(
            ".gateway_auth_client_id", GATEWAY_AUTH_CLIENT_ID
        )
        dockerfile = dockerfile.replace(
            ".gateway_auth_client_secret_resource",
            GATEWAY_AUTH_CLIENT_SECRET_RESOURCE,
        )

    with open(dockerfile_location, "w") as f:
        f.write(dockerfile)
