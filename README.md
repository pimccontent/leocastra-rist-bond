# LeoCastra RIST Bond

Ubuntu field kit that bonds modem and Wi-Fi paths with RIST Main profile. OBS or vMix sends one SRT stream to the kit. The kit sends one RIST path per uplink. Kit Ethernet stays the encoder LAN.

This is separate from Field OB SRTLA.

## Kit

Ubuntu Server 24.04, Docker, and host networking:

```bash
git clone https://github.com/pimccontent/leocastra-rist-bond.git
cd leocastra-rist-bond
sudo ./install.sh
```

Open `http://<kit-ip>:8089` from a laptop on the same LAN.

Bare metal, after `apt install python3 ffmpeg rist-tools iproute2`:

```bash
sudo cp leocastra-rist-bond.service /etc/systemd/system/
sudo systemctl enable --now leocastra-rist-bond
```

## Operator

1. In LeoCastra, edit the RIST stream and set Bond links to the number of modems (2 for two modems). Save.
2. Copy every Kit link line.
3. On the kit, open Settings and paste those lines. Leave uplinks on Auto. USB modems and Wi-Fi with an address are used. Ethernet is not.
4. Save and reconnect.
5. Copy the OBS URL from Status into OBS Custom server. Leave the stream key empty.

LeoCastra joins the links into one feed. Ingest runs that feed through Stream Studio. Relay publishes the SRT pull for the MCR.

Seamless sends a full copy on every path. Split shares packets across paths.

A 200 ms ceiling stays fixed. A higher ceiling lets a clean link stay near 200 ms.

## Studio

One Kit link line is one modem. Two lines are still one OBS feed. LeoCastra listens on both and joins them.
