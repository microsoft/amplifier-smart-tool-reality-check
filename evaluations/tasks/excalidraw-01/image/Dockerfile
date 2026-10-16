ARG EXCALIDRAW_VERSION=v0.18.1
ARG EXCALIDRAW_COMMIT=a2ec2889babf7d2295469c6d90ebe77fae57df84

FROM node:22-bookworm AS build
ARG EXCALIDRAW_VERSION
ARG EXCALIDRAW_COMMIT
WORKDIR /src
RUN git clone --depth 1 --branch "${EXCALIDRAW_VERSION}" https://github.com/excalidraw/excalidraw . \
    && test "$(git rev-parse HEAD)" = "${EXCALIDRAW_COMMIT}"
RUN yarn install --frozen-lockfile --network-timeout 600000
COPY scenario.patch /tmp/scenario.patch
RUN git apply /tmp/scenario.patch
# Source maps would put the patched source in the served files.
RUN yarn build:app:docker && find excalidraw-app/build -name '*.map' -delete

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY --from=build /src/excalidraw-app/build /usr/share/nginx/html
