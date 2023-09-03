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
        "click>=8",
        "cloud-sql-python-connector",
        "faiss-cpu",
        "flask>=1",
        "flask-cors>=3",
        "google-cloud-logging",
        "gunicorn",
        "markupsafe==2.0.1",
        "openai",
        "PolicyEngine-Core>=2.1,<3",
        "policyengine_canada==0.82.0",
        "policyengine-ng==0.5.1",
        "policyengine-il==0.1.0",
        "policyengine_uk==0.55.2",
        "policyengine_us==0.454.0",
        "pymysql",
        "redis",
        "rq",
        "sentence-transformers",
        "sqlalchemy>=1.4,<2",
        "streamlit",
        "Flask-Caching==2.0.2",
    ],
    # script policyengine-api-setup -> policyengine_api.setup_data:setup_data
    entry_points={
        "console_scripts": [
            "policyengine-api-setup=policyengine_api.setup_data:setup_data",
        ],
    },
)
