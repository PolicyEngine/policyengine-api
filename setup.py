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
        "PolicyEngine-Core>=1.10,<1.11",
        "policyengine-uk==0.38.3",
        "policyengine-us==0.197.3",
        "policyengine-canada==0.17.2",
        "gunicorn",
        "cloud-sql-python-connector",
        "google-cloud-logging",
        "pymysql",
        "sqlalchemy",
        "streamlit",
    ],
)
