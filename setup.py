from setuptools import setup, find_packages
from policyengine_api.constants import __version__

setup(
    name="policyengine-api",
    version=__version__,
    author="PolicyEngine",
    author_email="hello@policyengine.org",
    description="PolicyEngine API",
    packages=find_packages(),
    install_requires=[
        "anthropic",
        "click>=8,<9",
        "cloud-sql-python-connector",
        "faiss-cpu<1.8.0",
        "flask>=3,<4",
        "flask-cors>=5,<6",
        "google-cloud-logging",
        "gunicorn",
        "markupsafe>=3,<4",
        "openai",
        "policyengine_canada==0.96.2",
        "policyengine-ng==0.5.1",
        "policyengine-il==0.1.0",
        "policyengine_uk==2.17.0",
        "policyengine_us==1.180.1",
        "policyengine_core>=3.11.0",
        "pymysql",
        "redis",
        "rq",
        "sqlalchemy>=1.4,<2",
        "streamlit",
        "werkzeug",
        "Flask-Caching>=2,<3",
    ],
    extras_require={
        "dev": [
            "pytest-timeout",
        ],
    },
    # script policyengine-api-setup -> policyengine_api.setup_data:setup_data
    entry_points={
        "console_scripts": [
            "policyengine-api-setup=policyengine_api.setup_data:setup_data",
        ],
    },
)
