FROM rust:1.89
WORKDIR /app
COPY . .
RUN cargo build --release
EXPOSE 8085
CMD ["./target/release/docker_kmeans_server"]
