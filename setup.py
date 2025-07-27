from setuptools import setup, find_packages
from policyengine_api.constants import __version__

setup(
    name="policyengine-api",
    version=__version__,
    author="PolicyEngine",
    author_email="hello@policyengine.org",
    description="PolicyEngine API",
    packages=find_packages(),
    python_requires=">=3.10",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
    install_requires=[
        "numpy>=2.0,<3",  # Force NumPy 2.x for Python 3.13 compatibility
        "anthropic",
        "assertpy",
        "click>=8,<9",
        "cloud-sql-python-connector",
        "google-cloud-workflows",
        "faiss-cpu<1.12.0",
        "flask>=3,<4",
        "flask-cors>=6,<7",
        "google-cloud-logging",
        "gunicorn",
        "markupsafe>=3,<4",
        "openai",
        "policyengine_canada==0.96.3",
        "policyengine-ng==0.5.1",
        "policyengine-il==0.1.0",
        "policyengine_uk==2.43.2",
        "policyengine_us==1.351.2",
        "policyengine_core>=3.19.3",
        "policyengine>=0.6.0",
        "pydantic",
        "pymysql",
        "python-dotenv",
        "redis",
        "rq",
        "sqlalchemy>=2.0,<3",
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
