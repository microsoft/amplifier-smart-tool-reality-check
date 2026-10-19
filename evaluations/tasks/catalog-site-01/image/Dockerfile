ARG CATALOG_COMMIT=a573c23599df94c95e07745b4ebf8081daf16a2f

FROM python:3.12-slim AS build
ARG CATALOG_COMMIT
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init -q . \
    && git fetch -q --depth 1 https://github.com/microsoft/amplifier-smart-tools-catalog "${CATALOG_COMMIT}" \
    && git checkout -q FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${CATALOG_COMMIT}"
RUN pip install --no-cache-dir -r site/requirements.txt
COPY scenario.patch /tmp/scenario.patch
RUN git apply /tmp/scenario.patch
RUN python site/theme/build.py --family-owner microsoft --output /out/amplifier-smart-tools-catalog \
    && rm -f /out/amplifier-smart-tools-catalog/.nojekyll

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /out /usr/share/nginx/site
