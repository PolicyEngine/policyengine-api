#!/usr/bin/env bash

# Request the CI server credential: one Auth0 client-credentials access token
# for the Public API deployment this job tests, from the CI client in that
# environment's own Auth0 tenant (policyengine-api-staging.uk.auth0.com or
# policyengine-api.uk.auth0.com). push.yml runs it once in each job that calls
# a deployed Public API, as the step with id ci_server_token, and passes the
# token to the tests' step as CI_SERVER_ACCESS_TOKEN; the tests send it in
# Authorization: Bearer (tests/integration/deployed_api_credentials.py).
#
# The token is masked with ::add-mask:: before anything else, and written only
# to this step's output, "token". The step must print to the log, not to a
# file, or GitHub never reads the mask command. The client secret reaches curl
# on standard input, never in a command's arguments, and nothing prints it.
#
# The client must be one the tested deployment accepts, from the same GitHub
# environment: its tenant's issuer is PUBLIC_API_SERVER_AUTH_ISSUER, its
# audience is PUBLIC_API_AUTH_AUDIENCE and its ID is on
# PUBLIC_API_SERVER_CLIENT_IDS. Otherwise the deployment would refuse every
# request with 401, and a client of the other environment would get its token
# sent to this one.
#
# Environment:
#   CI_SERVER_AUTH0_DOMAIN         the tenant's host, with or without https://
#   CI_SERVER_AUTH0_CLIENT_ID      the CI client's ID
#   CI_SERVER_AUTH0_CLIENT_SECRET  the CI client's secret
#   CI_SERVER_AUTH0_AUDIENCE       the Public API's Auth0 API identifier
#   PUBLIC_API_SERVER_AUTH_ISSUER  the server-token issuer the deployment accepts
#   PUBLIC_API_AUTH_AUDIENCE       the audience the deployment accepts
#   PUBLIC_API_SERVER_CLIENT_IDS   the client IDs the deployment accepts
#   GITHUB_OUTPUT                  the step output file, set by GitHub Actions

set -euo pipefail

script_name="request_ci_server_token.sh"
required_names=(
  CI_SERVER_AUTH0_DOMAIN
  CI_SERVER_AUTH0_CLIENT_ID
  CI_SERVER_AUTH0_CLIENT_SECRET
  CI_SERVER_AUTH0_AUDIENCE
  PUBLIC_API_SERVER_AUTH_ISSUER
  PUBLIC_API_AUTH_AUDIENCE
  PUBLIC_API_SERVER_CLIENT_IDS
  GITHUB_OUTPUT
)

fail() {
  echo "${script_name}: $1" >&2
  exit 1
}

missing_names=()
for name in "${required_names[@]}"; do
  value="${!name:-}"
  # Only spaces and tabs, as for an Authorization header, count as unset.
  if [[ -z "${value//[[:blank:]]/}" ]]; then
    missing_names+=("${name}")
  fi
done
if (( ${#missing_names[@]} > 0 )); then
  fail "the CI server credential needs ${missing_names[*]}, from the job's GitHub environment (staging or production); the job must name that environment and pass them to this step"
fi

tenant_host="${CI_SERVER_AUTH0_DOMAIN#https://}"
tenant_host="${tenant_host%/}"
if [[ ! "${tenant_host}" =~ ^[A-Za-z0-9.-]+$ ]]; then
  fail "CI_SERVER_AUTH0_DOMAIN must be the Auth0 tenant's host name, such as policyengine-api-staging.uk.auth0.com"
fi

if [[ "https://${tenant_host}/" != "${PUBLIC_API_SERVER_AUTH_ISSUER%/}/" ]]; then
  fail "CI_SERVER_AUTH0_DOMAIN is not the tenant of PUBLIC_API_SERVER_AUTH_ISSUER, so the tested deployment would refuse its tokens; the CI client must belong to this job's environment"
fi
if [[ "${CI_SERVER_AUTH0_AUDIENCE}" != "${PUBLIC_API_AUTH_AUDIENCE}" ]]; then
  fail "CI_SERVER_AUTH0_AUDIENCE is not PUBLIC_API_AUTH_AUDIENCE, so the tested deployment would refuse its tokens"
fi
client_allowed=false
IFS=',' read -r -a allowed_client_ids <<< "${PUBLIC_API_SERVER_CLIENT_IDS}"
for allowed_client_id in "${allowed_client_ids[@]}"; do
  if [[ "${allowed_client_id}" == "${CI_SERVER_AUTH0_CLIENT_ID}" ]]; then
    client_allowed=true
  fi
done
if [[ "${client_allowed}" != true ]]; then
  fail "CI_SERVER_AUTH0_CLIENT_ID is not on PUBLIC_API_SERVER_CLIENT_IDS, so the tested deployment would refuse its tokens with 401"
fi

token_url="https://${tenant_host}/oauth/token"
# jq reads the secret from the environment, so it is in no command's arguments.
if ! token_response="$(
  jq --null-input --compact-output '{
      grant_type: "client_credentials",
      client_id: env.CI_SERVER_AUTH0_CLIENT_ID,
      client_secret: env.CI_SERVER_AUTH0_CLIENT_SECRET,
      audience: env.CI_SERVER_AUTH0_AUDIENCE
    }' \
    | curl --silent --show-error --fail \
        --retry 3 \
        --max-time 30 \
        --header "Content-Type: application/json" \
        --data-binary @- \
        "${token_url}"
)"; then
  fail "Auth0 refused or did not answer the token request to ${token_url}"
fi

access_token="$(
  jq --raw-output '.access_token // empty | strings' <<< "${token_response}" 2>/dev/null
)" || access_token=""
# A JWT is base64url text joined by dots; anything else could not be one
# output line, or could add another output.
if [[ ! "${access_token}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  fail "Auth0's answer from ${token_url} held no usable access token"
fi

echo "::add-mask::${access_token}"
printf 'token=%s\n' "${access_token}" >> "${GITHUB_OUTPUT}"
echo "Requested the CI server credential for ${CI_SERVER_AUTH0_AUDIENCE} from ${tenant_host}"
