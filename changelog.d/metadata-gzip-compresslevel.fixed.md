Lower the ASGI gzip compression level from 9 to 4 so large responses like /us/metadata spend seconds less CPU compressing on Cloud Run, restoring warm-latency parity with App Engine.
