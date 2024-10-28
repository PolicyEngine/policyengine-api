FROM python:3.10
ENV VIRTUAL_ENV /env
ENV PATH /env/bin:$PATH
RUN apt-get update && apt-get install -y build-essential checkinstall
RUN python3.10 -m pip install --upgrade pip --trusted-host pypi.python.org --trusted-host pypi.org --trusted-host files.pythonhosted.orgpip
RUN apt-get update && apt-get install -y redis-server
RUN pip install git+https://github.com/policyengine/policyengine-api
