# Docker guidance

The deployment actions build Docker images and deploy them to Google App Engine. The docker images themselves are based off a starter image (to save each API docker image having to spend 5 minutes installing the same dependencies). The starter image is the `Dockerfile` in this directory.

To update the starter image:
* `python setup.py sdist` to build the python package
* `twine upload dist/*` to upload the package to pypi as `policyengine-api`
* `cd gcp`
* `docker build .`
* `docker images` to get the image id (the most recent one should be the one you just built)
* `docker tag <image id> policyengine/policyengine-api`
* `docker push policyengine/policyengine-api`
