import json
from datetime import datetime
import inspect


def log(
    api: str,
    level: str,
    message: str,
    **data: dict,
):
    print(
        f"""LOG: {json.dumps(dict(
        api=api,
        level=level, 
        message=message, 
        data=data,
        timestamp=datetime.now().isoformat(),
        function=inspect.stack()[1].function,
        line_number=inspect.stack()[1].lineno,
    ))}"""
    )
