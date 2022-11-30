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
        "PolicyEngine-Core==1.10.7",
        "policyengine_uk @ git+https://github.com/policyengine/policyengine-uk@policyengine-dev",
        "policyengine_us @ git+https://github.com/policyengine/policyengine-us@policyengine-app-update",
    ],
)
