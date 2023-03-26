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
        "PolicyEngine-Core>=2,<3",
        "policyengine_uk==0.44.1",
        "policyengine_us==0.254.1",
        "policyengine_canada==0.42.3",
        "policyengine-ng==0.4.2",
        "gunicorn",
        "cloud-sql-python-connector",
        "google-cloud-logging",
        "pymysql",
        "sqlalchemy>=1.4,<2",
        "streamlit",
        "markupsafe==2.0.1",
    ],
)
