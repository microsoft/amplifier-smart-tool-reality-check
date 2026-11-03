# A task's machine with the universe's certificate authority added, so installs from github.com URLs the gateway
# answers for are trusted. `launch` mints the authority anew for each universe and provides it as the `dtu-ca` build
# context, so this is the only step that rebuilds on every launch.
ARG BASE=reality-check-evaluation-machine:eval
FROM ${BASE}
USER root
COPY --from=dtu-ca ca.crt /usr/local/share/ca-certificates/digital-twin-universe.crt
RUN update-ca-certificates
USER user
