# Define source folder
FROM policyengine/policyengine-api:latest

# Set all environment variables
ENV GOOGLE_APPLICATION_CREDENTIALS .gac.json
ENV POLICYENGINE_DB_PASSWORD .dbpw
ENV POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN .github_microdata_token
ENV ANTHROPIC_API_KEY .anthropic_api_key
ENV OPENAI_API_KEY .openai_api_key

# Set the working directory
WORKDIR /app

# Copy the application files
COPY . /app

# List contents of /app for debugging
RUN ls -la /app

# Make start.sh executable (if it exists)
RUN if [ -f /app/gcp/policyengine_api/start.sh ]; then chmod +x /app/start.sh; else echo "start.sh not found"; exit 1; fi

# Install dependencies and run tests
RUN cd /app && make install && make test

# Use full path to start.sh
CMD ["/bin/sh", "-c", "if [ -x /app/gcp/policyengine_api/start.sh ]; then /app/gcp/policyengine_api/start.sh; else echo 'start.sh not found or not executable'; exit 1; fi"]