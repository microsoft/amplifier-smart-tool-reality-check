# The LAN's router, as far as names go: the machines on the network are home-server-2 and home-server-2.lan, and
# every other name is forwarded. Docker's embedded DNS knows the other services by name and the internet's names.
FROM alpine:3.20
RUN apk add --no-cache coredns
COPY Corefile /etc/coredns/Corefile
CMD ["coredns", "-conf", "/etc/coredns/Corefile"]
