FROM gcr.io/google-appengine/python
ENV VIRTUAL_ENV /env
ENV PATH /env/bin:$PATH
# Install Python 3.9.13 from source
RUN apt-get update && apt-get install -y build-essential checkinstall
RUN apt-get install -y libreadline-gplv2-dev libncursesw5-dev libssl-dev libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev
RUN wget https://www.python.org/ftp/python/3.9.7/Python-3.9.7.tgz
RUN tar xzf Python-3.9.7.tgz
RUN cd Python-3.9.7 && ./configure --enable-optimizations
RUN cd Python-3.9.7 && make altinstall
RUN python3.9 -m pip install --upgrade pip
RUN pip install policyengine-api
