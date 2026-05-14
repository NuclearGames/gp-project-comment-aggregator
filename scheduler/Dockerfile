FROM alpine:3.19

RUN apk add --no-cache docker-cli supercronic

COPY crontab /etc/crontab

CMD ["supercronic", "/etc/crontab"]
