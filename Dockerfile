FROM gcr.io/google-appengine/python
RUN virtualenv /env -p python3.7
ENV VIRTUAL_ENV /env
ENV PATH /env/bin:$PATH
ENV GOOGLE_APPLICATION_CREDENTIALS .gac.json
ENV POLICYENGINE_DB_PASSWORD .dbpw.json
ADD . /app
RUN python -m pip install --upgrade pip
RUN cd /app && make install
CMD gunicorn -b :$PORT policyengine_api.api --timeout 240
