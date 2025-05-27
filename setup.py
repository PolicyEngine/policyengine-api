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
        "assertpy",
        "click>=8,<9",
        "cloud-sql-python-connector",
        "google-cloud-workflows",
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
        "policyengine_uk==2.28.1",
        "policyengine_us==1.289.1",
        "policyengine_core>=3.16.6",
        "policyengine>=0.3.0",
        "pydantic",
        "pymysql",
        "python-dotenv",
        "redis",
        "rq",
        "sqlalchemy>=1.4,<2",
        "streamlit",
        "werkzeug",
        "Flask-Caching>=2,<3",
        "google-cloud-logging>=3,<4",
    ],
    extras_require={
        "dev": ["pytest-timeout", "coverage", "pytest-snapshot"],
    },
    # script policyengine-api-setup -> policyengine_api.setup_data:setup_data
    entry_points={
        "console_scripts": [
            "policyengine-api-setup=policyengine_api.setup_data:setup_data",
        ],
    },
)
