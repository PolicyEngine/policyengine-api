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
        "flask>=1",
        "flask-cors>=3",
        "PolicyEngine-Core>=2.0.3,<3",
        "policyengine_uk==0.49.0",
        "policyengine_us==0.320.1",
        "policyengine_canada==0.61.0",
        "policyengine-ng==0.5.1",
        "gunicorn",
        "cloud-sql-python-connector",
        "google-cloud-logging",
        "pymysql",
        "sqlalchemy>=1.4,<2",
        "streamlit",
        "markupsafe==2.0.1",
        "openai",
        "rq",
        "redis",
        "sentence-transformers",
        "faiss-cpu",
    ],
    # script policyengine-api-setup -> policyengine_api.setup_data:setup_data
    entry_points={
        "console_scripts": [
            "policyengine-api-setup=policyengine_api.setup_data:setup_data",
        ],
    },
)
