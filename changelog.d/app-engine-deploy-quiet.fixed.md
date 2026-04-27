Fixed staged App Engine deploy automation to use `gcloud app deploy --quiet` instead of piping `yes`, preventing false CI failures after successful deployments.
