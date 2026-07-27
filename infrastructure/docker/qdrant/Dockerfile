FROM busybox:1.37.0 AS health-tools

FROM qdrant/qdrant:v1.18.2

COPY --from=health-tools /bin/busybox /usr/local/bin/healthcheck
