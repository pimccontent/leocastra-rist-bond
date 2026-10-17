FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 ffmpeg iproute2 rist-tools ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/leocastra-rist-bond
COPY bond_plan.py status-server.py ./
COPY web ./web

ENV WEB_ROOT=/opt/leocastra-rist-bond/web
ENV CONFIG_DIR=/var/lib/leocastra-rist
ENV STATUS_PORT=8089
ENV FFMPEG_BIN=ffmpeg
ENV RISTSENDER_BIN=ristsender
EXPOSE 8089

CMD ["python3", "status-server.py"]
