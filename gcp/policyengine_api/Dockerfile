FROM policyengine/policyengine-api:latest
ENV GOOGLE_APPLICATION_CREDENTIALS .gac.json
ENV POLICYENGINE_DB_PASSWORD .dbpw
ENV POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN .github_microdata_token
ENV ANTHROPIC_API_KEY .anthropic_api_key
ENV OPENAI_API_KEY .openai_api_key
ADD . /app
RUN cd /app && make install && make test
CMD ./start.sh
