FROM us-docker.pkg.dev/cloud-ops-agents-artifacts/google-cloud-opentelemetry-collector/otelcol-google:0.160.0

COPY config.yaml /etc/otelcol-google/config.yaml

ENTRYPOINT ["/otelcol-google"]
CMD ["--config=/etc/otelcol-google/config.yaml"]
