# PolicyEngine API

This is the official back-end service of PolicyEngine, a non-profit with the mission of computing the impact of public policy for the world. <br/><br/>

# Prerequisites

Running or editing the API locally will require a Python virtual environment, either through the Python `venv` command or a secondary package like `conda`. For more information on how to do this, check out the documentation for `venv` [here](https://docs.python.org/3/library/venv.html) and this overview blog post for `conda` [here](https://uoa-eresearch.github.io/eresearch-cookbook/recipe/2014/11/20/conda/).

Python 3.10 or 3.11 is required.

# Contributing

## Choosing an Issue

All of our code changes are made against a GitHub issue. If you're new to the project, go to **Issues** and search for good first issues `label: "good first issue"`.

To prevent confusion, we typically assign contributors, but reserve the right to unassign or reassign if we don't receive any updates on an issue for 3 or more weeks. That said, there is no requirement to be assigned before contributing - if you see an open issue that no one's opened a PR against, it's all yours! Feel free to make some edits, then open a PR, as described below.

## Setting Up

### 1. Clone the repo

```
git clone https://github.com/PolicyEngine/policyengine-api.git
```

To contribute, clone the repository instead of forking it and then request to be added as a contributor. Create a new branch and get started!

### 2. Activate your virtual environment

### 3. Install dependencies

```
make install
make setup-env
```

### 3a. Configure environment variables

`make setup-env` creates a local `.env` from `.env.example`. At minimum, local development expects values for:

- `POLICYENGINE_DB_PASSWORD`
- `POLICYENGINE_DB_INSTANCE_CONNECTION_NAME`
- `POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN`
- `OPENAI_API_KEY`
- `HUGGING_FACE_TOKEN`

The database settings must resolve to an explicit durable development MySQL
database (or an authorized Cloud SQL development target). `FLASK_DEBUG` does
not select or create SQLite, and the application never bootstraps
`policyengine.db`.

If you need a local Google credential file for ADC, uncomment and set:

- `GOOGLE_APPLICATION_CREDENTIALS`

Keep that commented unless you are pointing at a real local credential file. The deployed App Engine service uses its attached service account instead.

If you are running against an auth-protected simulation gateway outside the managed deploy path, you may also need:

- `SIM_ENTRYPOINT` (`old_gateway_direct` or `cloud_run_simulation_entrypoint`)
- the URL selected by `SIM_ENTRYPOINT`:
  - `OLD_SIMULATION_GATEWAY_URL` for `old_gateway_direct`; or
  - `SIMULATION_ENTRYPOINT_URL` for `cloud_run_simulation_entrypoint`
- `GATEWAY_AUTH_REQUIRED`
- `GATEWAY_AUTH_ISSUER`
- `GATEWAY_AUTH_AUDIENCE`
- `GATEWAY_AUTH_CLIENT_ID`
- one of `GATEWAY_AUTH_CLIENT_SECRET` or `GATEWAY_AUTH_CLIENT_SECRET_RESOURCE`

Managed App Engine deploys render non-secret runtime configuration and Secret
Manager resource names into `app.yaml`. Application secret values are resolved
in memory by the attached runtime service account before Gunicorn starts; they
are never written into the build context or image layers.

### 4. Start a server on localhost to see your changes

Run:

```
make debug
```

Now you're ready to start developing!

NOTE: If you are using Airpods or other Apple bluetooth products, you may get an error related to the port. If this is the case, define a specific port in the debug statement in the Makefile. For example:

```
debug:
	FLASK_APP=policyengine_api.api FLASK_DEBUG=1 flask run --without-threads --port=5001
```

If you get a CORS error try:

In api.py, comment out

```
CORS(app)
```

Add

```
CORS(app, resources={r"/*": {"origins": "*"}})
```

A simple API get call you can send in Postman to make sure it is working as expected is:

```
http://127.0.0.1:5001/us/policy/2
```

### 5. To test in combination with policyengine-app:

1. In policyengine-app/src/api/call.js, comment out

```
const POLICYENGINE_API = "https://api.policyengine.org";
```

And add

```
const POLICYENGINE_API = "http://127.0.0.1:5001" (or the relevant port where the server is running)
```

2. Start server as described above
3. Start app as described in policyengine-app/README.md

NOTE: Any output that needs to be calculated will not work. Therefore, only household output can be tested with this setup.

### 6. Testing calculations

Redis is required for API cache paths, including budget-window economy requests. The budget-window endpoint uses Redis for completed-result caching and in-flight batch deduplication; if Redis is unavailable, completed results are recoverable misses while ownership and deduplication operations fail closed instead of launching duplicate work.

To test anything that utilizes Redis or the API's service workers (e.g. anything that requires society-wide calculations with the policy calculator), you'll also need to complete the following steps:

1. Start Redis

- Install Redis:

```
brew install redis
```

- Start Redis:

```
redis-server
```

Configure that separate local process explicitly; there is no localhost
fallback:

```sh
export RUNTIME_CACHE_MODE=local
export RUNTIME_CACHE_URL=redis://127.0.0.1:6379/0
export RUNTIME_CACHE_ENVIRONMENT=local-dev
export RUNTIME_CACHE_SERVICE=api
```

Deployed mode instead requires an authenticated `rediss://` URL and the
Memorystore instance CA. Do not use production cache credentials locally.

2. Start the API

Run the below

```
FLASK_DEBUG=1 python -m flask --app policyengine_api.api run
```

App Engine and Cloud Run images start only Gunicorn. Deployed revisions connect
to their environment's managed Memorystore instance and never launch Redis in
the application container.

NOTE: Calculations are not possible in the uk app without access to a specific dataset. Expect an error: "ValueError: Invalid response code 404 for url https://api.github.com/repos/policyengine/non-public-microdata/releases/tags/uk-2024-march-efo."

## Testing, Formatting, Changelogging

You've finished your contribution, but now what? Before opening a PR, we ask contributors to do three things.

### Step 1: Testing

To test your changes against our series of automated tests, run

```
make debug-test
```

NOTE: Running the command `make test` will fail, as this command is utilized by the deployed app to run tests and requires passwords to the production database.

We require that you add tests for any new features or bugfixes. Our tests are written in the Python standard, [Pytest](https://docs.pytest.org/en/7.1.x/getting-started.html), and will be run again against the production environment, as well.

### Step 2: Formatting

In addition to the tests, we use [Black](https://github.com/psf/black) to lint our codebase, so before opening a pull request, Step 2 is to lint the code by running

```
make format
```

This will automatically format the code for you; no need to do anything else.

### Step 3: Changelogging

Finally, we ask contributors to make it clear for our users what changes have been made by contributing to a changelog. This changelog is formatted in YAML and describes the changes you've made to the code. This should follow the below format:

```
- bump: {major, minor, patch}
  changes:
    {added, removed, changed, fixed}:
    - <variable or program>
```

For more info on the syntax, check out the [semantic versioning docs](https://www.semver.org) and [keep a changelog](https://www.keepachangelog.com).

Write your changelog info into the empty file called `changelog_entry.yaml`. When you open your PR, this will automatically be added to the overall changelog.

## Opening a Pull Request

Now you've finished your contribution! Please open a pull request (PR) from your branch and request review. At times, it may take some time for the team to review your PR, especially for larger contributions, so please be patient--we will be sure to get to it.

In the first line of your PR, please make sure to include the following:

```
Fixes #{issue_number}
```

This makes it much easier for us to maintain and prune our issue board.

Please try to be detailed in your PRs about the changes you made and why you made them. You may find yourself looking back at them for reference in the future, or needing insight about someone else's changes. Save yourself a conversation and write it all in the PR!

Here are some [best practices](https://deepsource.io/blog/git-best-practices/) for using Git.

When you're ready for review, switch the PR from `Draft` to `Ready for review` and add a contributor as a reviewer.

# License

Distributed under the AGPL License. See `LICENSE` for more info.

# Acknowledgements

Thanks to Othneil Drew for his [README template](https://github.com/othneildrew/Best-README-Template).
