FROM nikhilwoodruff/policyengine-api:latest
ENV GOOGLE_APPLICATION_CREDENTIALS .gac.json
ENV POLICYENGINE_DB_PASSWORD .dbpw
ENV POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN .github_microdata_token
ADD . /app
RUN cd /app && make install && make test-compute
CMD gunicorn -b :$PORT policyengine_api.compute_api --timeout 300 --workers 5 --log-level debug
