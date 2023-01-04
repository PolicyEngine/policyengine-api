# Use Python 3.9.13
FROM python:3.9.13-slim-buster
ENV VIRTUAL_ENV /env
ENV PATH /env/bin:$PATH
ENV GOOGLE_APPLICATION_CREDENTIALS .gac.json
ENV POLICYENGINE_DB_PASSWORD .dbpw
ADD . /app
RUN python3 -m pip install --upgrade pip
RUN cd /app && make install && make test
CMD gunicorn -b :$PORT policyengine_api.compute_api --timeout 240 --workers 1 --log-level=debug
