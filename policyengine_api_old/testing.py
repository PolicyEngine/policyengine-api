from flask import Request
import time
import yaml
import os
import datetime

start_time = time.time()
session_id = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


class YamlLoggerMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        # Record the request
        req = Request(environ)

        # Record the response
        response = self.app(environ, start_response)

        response_data = {}
        status_code = 200

        # Save the request-response to a YAML file
        timestamp = int(time.time())
        file_name = f"{(timestamp - start_time) * 100:.0f}_{req.path.strip('/').replace('/', '-')}.yaml"

        data = {
            "name": file_name,  # You can customize this field
            "endpoint": req.path,
            "method": req.method,
            "data": req.form.to_dict() if req.method == "POST" else {},
            "response": {"data": response_data, "status": status_code},
        }
        output_dir = f"tests/api/auto/session_{session_id}"
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, file_name)

        with open(file_path, "w") as f:
            yaml.dump(data, f)

        return response
