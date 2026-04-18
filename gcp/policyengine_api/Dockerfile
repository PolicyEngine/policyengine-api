FROM python:3.11

RUN apt-get update && apt-get install -y build-essential redis-server && rm -rf /var/lib/apt/lists/*

ENV GOOGLE_APPLICATION_CREDENTIALS .gac.json
ENV POLICYENGINE_DB_PASSWORD .dbpw
ENV POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN .github_microdata_token
ENV ANTHROPIC_API_KEY .anthropic_api_key
ENV OPENAI_API_KEY .openai_api_key
ENV HUGGING_FACE_TOKEN .hugging_face_token
ENV CREDENTIALS_JSON_API_V2 .credentials_json_api_v2

WORKDIR /app

# Copy application
ADD . /app

# Make start.sh executable
RUN chmod +x /app/start.sh

RUN cd /app && make install && make test

# Use full path to start.sh
CMD ["/bin/sh", "/app/start.sh"]
