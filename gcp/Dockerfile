FROM gcr.io/google-appengine/python
ENV VIRTUAL_ENV /env
ENV PATH /env/bin:$PATH
# Install Python 3.9.4 from source
RUN apt-get update && apt-get install -y build-essential checkinstall
RUN apt-get install -y libreadline-gplv2-dev libncursesw5-dev libssl-dev libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev
RUN wget https://www.python.org/ftp/python/3.9.4/Python-3.9.4.tgz
RUN tar xzf Python-3.9.4.tgz
RUN cd Python-3.9.4 && ./configure --enable-optimizations
RUN cd Python-3.9.4 && make altinstall
RUN python3.9 -m pip install --upgrade pip
RUN apt-get update && apt-get install -y redis-server
RUN pip install git+https://github.com/policyengine/policyengine-api
