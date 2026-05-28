#!/usr/bin/env python3
"""Download and convert v2ray geoip.dat into Shadowrocket rule-set files.

The geoip.dat file is a protobuf-encoded GeoIPList. This script uses a
small protobuf wire-format reader so the scheduled workflow does not need any
third-party Python packages.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_URL = "https://raw.githubusercontent.com/Loyalsoldier/v2ray-rules-dat/release/geoip.dat"
DEFAULT_OUTPUT_DIR = "rules-ip"

_FILENAME_SAFE = re.compile(r"[^a-z0-9._!-]+")


@dataclass(frozen=True)
class CIDR:
    ip: bytes
    prefix: int


@dataclass(frozen=True)
class GeoIP:
    code: str
    cidrs: tuple[CIDR, ...]


class ProtoReader:
    """Minimal protobuf wire-format reader for length-delimited messages."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def read_varint(self) -> int:
        shift = 0
        value = 0
        while True:
            if self.pos >= len(self.data):
                raise ValueError("unexpected end of data while reading varint")
            byte = self.data[self.pos]
            self.pos += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
            shift += 7
            if shift >= 64:
                raise ValueError("varint is too long")

    def read_key(self) -> tuple[int, int]:
        key = self.read_varint()
        return key >> 3, key & 0x07

    def read_bytes(self) -> bytes:
        length = self.read_varint()
        end = self.pos + length
        if end > len(self.data):
            raise ValueError("length-delimited field exceeds input size")
        value = self.data[self.pos:end]
        self.pos = end
        return value

    def skip(self, wire_type: int) -> None:
        if wire_type == 0:  # varint
            self.read_varint()
        elif wire_type == 1:  # 64-bit
            self.pos += 8
        elif wire_type == 2:  # length-delimited
            self.read_bytes()
        elif wire_type == 5:  # 32-bit
            self.pos += 4
        else:
            raise ValueError(f"unsupported protobuf wire type: {wire_type}")
        if self.pos > len(self.data):
            raise ValueError("field exceeds input size")


def parse_cidr(data: bytes) -> CIDR:
    """Parse v2ray GeoIP CIDR message.

    v2ray geoip CIDR fields:
    - field 1: ip bytes
    - field 2: prefix uint32
    """

    reader = ProtoReader(data)
    ip = b""
    prefix = 0

    while not reader.eof():
        field, wire_type = reader.read_key()
        if field == 1 and wire_type == 2:
            ip = reader.read_bytes()
        elif field == 2 and wire_type == 0:
            prefix = reader.read_varint()
        else:
            reader.skip(wire_type)

    return CIDR(ip=ip, prefix=prefix)


def parse_geoip(data: bytes) -> GeoIP:
    """Parse v2ray GeoIP message.

    v2ray geoip GeoIP fields:
    - field 1: country_code string
    - field 2: repeated CIDR
    - field 3: inverse_match bool, ignored here
    """

    reader = ProtoReader(data)
    code = ""
    cidrs: list[CIDR] = []

    while not reader.eof():
        field, wire_type = reader.read_key()
        if field == 1 and wire_type == 2:
            code = reader.read_bytes().decode("utf-8")
        elif field == 2 and wire_type == 2:
            cidr = parse_cidr(reader.read_bytes())
            if cidr.ip:
                cidrs.append(cidr)
        else:
            reader.skip(wire_type)

    return GeoIP(code=code, cidrs=tuple(cidrs))


def parse_geoip_list(data: bytes) -> list[GeoIP]:
    """Parse v2ray GeoIPList message.

    v2ray geoip GeoIPList fields:
    - field 1: repeated GeoIP
    """

    reader = ProtoReader(data)
    entries: list[GeoIP] = []

    while not reader.eof():
        field, wire_type = reader.read_key()
        if field == 1 and wire_type == 2:
            entry = parse_geoip(reader.read_bytes())
            if entry.code:
                entries.append(entry)
        else:
            reader.skip(wire_type)

    return entries


def cidr_to_text(cidr: CIDR) -> str | None:
    try:
        address = ipaddress.ip_address(cidr.ip)
        network = ipaddress.ip_network((address, cidr.prefix), strict=False)
    except ValueError:
        return None

    return f"{network.network_address}/{network.prefixlen}"


def shadowrocket_lines(entry: GeoIP) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()

    for cidr in entry.cidrs:
        cidr_text = cidr_to_text(cidr)
        if cidr_text is None:
            continue

        # Shadowrocket rule-set syntax uses IP-CIDR for both IPv4 and IPv6.
        # Do not append no-resolve here; users can add it at include/use time.
        line = f"IP-CIDR,{cidr_text}"
        if line not in seen:
            seen.add(line)
            lines.append(line)

    return lines


def normalize_ruleset_name(code: str) -> str:
    normalized = _FILENAME_SAFE.sub("_", code.strip().lower()).strip(".-_")
    if not normalized:
        raise ValueError(f"invalid geoip code for filename: {code!r}")
    return normalized


def write_rulesets(entries: Iterable[GeoIP], output_dir: Path, extension: str) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    if extension:
        for stale_file in output_dir.glob(f"*{extension}"):
            stale_file.unlink()

    count = 0

    for entry in entries:
        ruleset_name = normalize_ruleset_name(entry.code)
        path = output_dir / f"{ruleset_name}{extension}"
        lines = shadowrocket_lines(entry)
        content = "\n".join(lines)
        if content:
            content += "\n"
        path.write_text(content, encoding="utf-8", newline="\n")
        count += 1

    return count


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "ruleset-geoip-converter"})
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())


def load_geoip_dat(args: argparse.Namespace) -> bytes:
    if args.input:
        return Path(args.input).read_bytes()

    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        download(args.url, temp_path)
        return temp_path.read_bytes()
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert v2ray geoip.dat into Shadowrocket rule-set files."
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("GEOIP_DAT_URL", DEFAULT_URL),
        help=f"geoip.dat URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--input",
        help="read a local geoip.dat file instead of downloading one",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"directory for generated rule-set files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--extension",
        default=".list",
        help="generated file extension; use an empty string for extensionless files",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    data = load_geoip_dat(args)
    entries = parse_geoip_list(data)
    count = write_rulesets(entries, Path(args.output_dir), args.extension)
    print(f"Generated {count} Shadowrocket IP rule-set files in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
