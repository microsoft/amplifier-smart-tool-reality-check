# The developer machine with what running eShop takes, as its README sets it up: the .NET SDK its global.json
# selects, ICU for .NET to start, and the Aspire CLI at the version aspire.config.json selects. Ubuntu's own .NET 10
# package is a 1xx SDK, below global.json's 10.0.302, so the SDK comes from Microsoft's image.
FROM reality-check-evaluation-machine:eval
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends libicu74 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=mcr.microsoft.com/dotnet/sdk:10.0.302-noble /usr/share/dotnet /usr/share/dotnet
RUN ln -s /usr/share/dotnet/dotnet /usr/bin/dotnet
USER user
ENV DOTNET_ROOT=/usr/share/dotnet DOTNET_NOLOGO=1 PATH=/home/user/.dotnet/tools:$PATH
RUN dotnet tool install --global Aspire.Cli --version 13.6.0
