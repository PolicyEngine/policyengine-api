FROM python:3.11

RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy application
ADD . /app

# Make start.sh executable
RUN chmod +x /app/start.sh

RUN cd /app && make install

# Use full path to start.sh
CMD ["/bin/sh", "/app/start.sh"]
