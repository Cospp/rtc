FROM golang:1.24-alpine AS builder

WORKDIR /src

COPY relay/go.mod relay/go.sum* ./
RUN go mod download

COPY relay/. ./
RUN go build -o /out/relay .

FROM alpine:3.21

WORKDIR /app

COPY --from=builder /out/relay /usr/local/bin/relay

EXPOSE 8080

CMD ["relay"]
