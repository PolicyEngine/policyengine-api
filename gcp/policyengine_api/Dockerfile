FROM python:3.9
ENV VIRTUAL_ENV /env
ENV PATH /env/bin:$PATH
ENV GOOGLE_APPLICATION_CREDENTIALS .gac.json
ENV POLICYENGINE_DB_PASSWORD .dbpw
ADD . /app
RUN python -m pip install --upgrade pip
RUN cd /app && pip install -e . && pytest tests -v
CMD gunicorn -b :$PORT policyengine_api.api --timeout 240 --workers 1 --threads 1 --log-level=debug