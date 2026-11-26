FROM rust:1.82-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    gfortran \
    python3 \
    python3-pip \
    nodejs \
    npm \
    gh \
    && rm -rf /var/lib/apt/lists/*

RUN rustup target add wasm32-unknown-unknown \
    && cargo install wasm-pack

WORKDIR /workspace