# The developer machine with what building Microsoft Edit from source takes: a C compiler, ICU, and Rust through
# rustup at the workspace's rust-version.
FROM reality-check-evaluation-machine:eval
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libicu-dev \
    && rm -rf /var/lib/apt/lists/*
USER user
RUN curl -fsSL https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init -o /tmp/rustup-init \
    && curl -fsSL https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init.sha256 \
        | sed 's#\*\?/\?[^ ]*$#/tmp/rustup-init#' | sha256sum -c - \
    && chmod +x /tmp/rustup-init \
    && /tmp/rustup-init -y --profile minimal --default-toolchain 1.93 \
    && rm /tmp/rustup-init
ENV PATH=/home/user/.cargo/bin:$PATH
