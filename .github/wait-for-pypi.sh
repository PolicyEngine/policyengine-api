#! /usr/bin/env bash

COMMIT_MSG=$(git log -1 --pretty=%B)
if ! echo "$COMMIT_MSG" | grep -qi "update policyengine bundle to"; then
  echo "Skipping PyPI wait — not an automated PolicyEngine bundle update commit."
  exit 0
fi

VERSION=$(grep -oP "(?<=policyengine\\[models\\]==)[0-9\.]+" pyproject.toml)
echo "Waiting for policyengine version $VERSION to appear on PyPI..."

for i in {1..6}; do
  if curl -s https://pypi.org/pypi/policyengine/json | jq -e ".releases[\"$VERSION\"]" > /dev/null; then
    echo "Version $VERSION is available on PyPI!"
    exit 0
  fi
  echo "Version $VERSION not yet available. Retrying in 10 seconds..."
  sleep 10
done

echo "Timed out waiting for policyengine version $VERSION to become available on PyPI"
exit 1
