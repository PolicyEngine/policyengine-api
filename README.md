# PolicyEngine API

This is the official back-end service of PolicyEngine, a non-profit with the mission of computing the impact of public policy for the world. <br/><br/>

# Prerequisites

Running or editing the API locally requires Python and a virtual environment. Prefer [`uv`](https://docs.astral.sh/uv/) for local setup, especially in fresh worktrees.

Use the Python version in `.python-version`.

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

### 2. Bootstrap a fresh checkout or worktree

```
make bootstrap-dev
```

This creates a local virtual environment, installs development dependencies, and copies `.env.example` to `.env` if needed.

If you already have an activated environment and just need dependencies, you can still run:

```
make install
```

### 3. Start a server on localhost to see your changes

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

### 4. To test in combination with policyengine-app:

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

### 5. Testing calculations

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

2. Start the API service worker

Run the below

```
FLASK_DEBUG=1 python policyengine_api/worker.py
```

NOTE: Calculations are not possible in the uk app without access to a specific dataset. Expect an error: "ValueError: Invalid response code 404 for url https://api.github.com/repos/policyengine/non-public-microdata/releases/tags/uk-2024-march-efo."

## Testing, Formatting, Changelogging

You've finished your contribution, but now what? Before opening a PR, we ask contributors to do three things.

### Step 1: Testing

For the fast PR preflight checks that catch the most common CI failures, run:

```
make pre-pr
```

This runs:

- `make lint`
- `make check-changelog`

To run the main automated test suite locally, run:

```
make test
```

This suite mirrors the main CI test job and may require the same credentials and environment variables.

If you want the broader local test run with verbose output while iterating, run:

```
make debug-test
```

We require that you add tests for any new features or bugfixes. Our tests are written in the Python standard, [Pytest](https://docs.pytest.org/en/7.1.x/getting-started.html), and will be run again against the production environment, as well.

### Step 2: Formatting

In addition to the tests, we use [Ruff](https://docs.astral.sh/ruff/) for formatting. To auto-format the repo, run:

```
make format
```

To run the same format check used in CI without rewriting files, run:

```
make lint
```

### Step 3: Changelogging

Finally, we ask contributors to make it clear for our users what changes have been made by adding a changelog fragment in `changelog.d/`.

Use one of these suffixes:

- `added`
- `changed`
- `fixed`
- `removed`
- `breaking`

For example:

```
echo "Honor explicit economy dataset selection in society-wide calculations." > changelog.d/my-branch.fixed.md
```

To check that a fragment exists before you push, run:

```
make check-changelog
```

## Fresh Worktree Notes

- Prefer `make` targets or `python -m ...` commands over hardcoded paths like `./.venv/bin/pytest`.
- In a new worktree, run `make bootstrap-dev` before trying to lint or test.
- If you are unsure what to run before pushing, use `make pre-pr`.

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
