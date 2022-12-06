FROM gcr.io/google-appengine/python
RUN virtualenv /env -p python3.7
ENV VIRTUAL_ENV /env
ENV PATH /env/bin:$PATH
ENV GOOGLE_APPLICATION_CREDENTIALS .gac.json
ENV POLICYENGINE_DB_PASSWORD $(cat .dbpw.json)
ADD . /app
RUN python -m pip install --upgrade pip
RUN cd /app && make install && make test
CMD gunicorn -b :$PORT policyengine_api.api --timeout 240 --workers 1 --threads 1 --log-level=debug
