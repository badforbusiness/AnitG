# Base image
FROM ubuntu:22.04

# Avoid tzdata prompts
ENV DEBIAN_FRONTEND=noninteractive

# GraXpert version (override at build time: docker build --build-arg GRAXPERT_VERSION=3.0.3 .)
ARG GRAXPERT_VERSION=3.0.2

# Install system dependencies
RUN apt-get update && apt-get install -y \
    software-properties-common \
    wget \
    unzip \
    python3 \
    python3-pip \
    libgl1 \
    libglib2.0-0 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Install Siril
RUN add-apt-repository -y ppa:lock042/siril \
    && apt-get update \
    && apt-get install -y siril \
    && rm -rf /var/lib/apt/lists/*

# Install GraXpert
RUN wget -q https://github.com/Steffenhir/GraXpert/releases/download/${GRAXPERT_VERSION}/graxpert-linux-amd64.zip -O graxpert.zip \
    && unzip graxpert.zip -d /opt/graxpert \
    && rm graxpert.zip \
    && find /opt/graxpert -type f -name "GraXpert*" -executable -exec ln -s {} /usr/local/bin/graxpert \;

# Install Python requirements (Pillow not needed - GUI only runs on host Windows)
RUN pip3 install astropy numpy scipy

# Setup workspace
WORKDIR /app
COPY run_pipeline.py /app/run_pipeline.py

# Entrypoint wrapper to pass arguments
ENTRYPOINT ["python3", "/app/run_pipeline.py"]
