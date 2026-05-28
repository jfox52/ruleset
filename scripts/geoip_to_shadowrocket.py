#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Convert v2ray geoip.dat to Shadowrocket IP ruleset.

Input:
  - geoip.dat

Output:
  - rules-ip/<country>.list

Shadowrocket rule format:
  IP-CIDR,1.2.3.0/24,no-resolve
  IP-CIDR6,2001:db8::/32,no-resolve
"""

import argparse
import ipaddress
import os
import shutil
from dataclasses import dataclass
from typing import List, Tuple


WIRE_VARINT = 0
WIRE_LEN = 2


@dataclass
class CIDR:
    ip: bytes
    prefix: int


@dataclass
class GeoIPEntry:
    country_code: str
    cidrs: List[CIDR]


def read_varint(data: bytes, pos: int) -> Tuple[int, int]:
    value = 0
    shift = 0

    while True:
        if pos >= len(data):
            raise ValueError("Unexpected EOF while reading varint")

        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift

        if not (b & 0x80):
            return value, pos

        shift += 7
        if shift > 64:
            raise ValueError("Varint is too long")


def read_key(data: bytes, pos: int) -> Tuple[int, int, int]:
    key, pos = read_varint(data, pos)
    field_number = key >> 3
    wire_type = key & 0x07
    return field_number, wire_type, pos


def skip_field(data: bytes, pos: int, wire_type: int) -> int:
    if wire_type == WIRE_VARINT:
        _, pos = read_varint(data, pos)
        return pos

    if wire_type == WIRE_LEN:
        length, pos = read_varint(data, pos)
        return pos + length

    raise ValueError(f"Unsupported wire type: {wire_type}")


def parse_cidr(data: bytes) -> CIDR:
    pos = 0
    ip = b""
    prefix = 0

    while pos < len(data):
        field_number, wire_type, pos = read_key(data, pos)

        if field_number == 1 and wire_type == WIRE_LEN:
            length, pos = read_varint(data, pos)
            ip = data[pos:pos + length]
            pos += length

        elif field_number == 2 and wire_type == WIRE_VARINT:
            prefix, pos = read_varint(data, pos)

        else:
            pos = skip_field(data, pos, wire_type)

    return CIDR(ip=ip, prefix=prefix)


def parse_geoip_entry(data: bytes) -> GeoIPEntry:
    pos = 0
    country_code = ""
    cidrs: List[CIDR] = []

    while pos < len(data):
        field_number, wire_type, pos = read_key(data, pos)

        # message GeoIP {
        #   string country_code = 1;
        #   repeated CIDR cidr = 2;
        # }
        if field_number == 1 and wire_type == WIRE_LEN:
            length, pos = read_varint(data, pos)
            country_code = data[pos:pos + length].decode("utf-8")
            pos += length

        elif field_number == 2 and wire_type == WIRE_LEN:
            length, pos = read_varint(data, pos)
            cidrs.append(parse_cidr(data[pos:pos + length]))
            pos += length

        else:
            pos = skip_field(data, pos, wire_type)

    return GeoIPEntry(country_code=country_code, cidrs=cidrs)


def parse_geoip_list(data: bytes) -> List[GeoIPEntry]:
    pos = 0
    entries: List[GeoIPEntry] = []

    while pos < len(data):
        field_number, wire_type, pos = read_key(data, pos)

        # message GeoIPList {
        #   repeated GeoIP entry = 1;
        # }
        if field_number == 1 and wire_type == WIRE_LEN:
            length, pos = read_varint(data, pos)
            entries.append(parse_geoip_entry(data[pos:pos + length]))
            pos += length

        else:
            pos = skip_field(data, pos, wire_type)

    return entries


def cidr_to_shadowrocket_rule(cidr: CIDR) -> str:
    if len(cidr.ip) == 4:
        network = ipaddress.IPv4Network((int.from_bytes(cidr.ip, "big"), cidr.prefix), strict=False)
        return f"IP-CIDR,{network},no-resolve"

    if len(cidr.ip) == 16:
        network = ipaddress.IPv6Network((int.from_bytes(cidr.ip, "big"), cidr.prefix), strict=False)
        return f"IP-CIDR6,{network},no-resolve"

    raise ValueError(f"Invalid IP length: {len(cidr.ip)}")


def safe_filename(country_code: str) -> str:
    return country_code.strip().lower().replace(":", "-")


def write_rules(entries: List[GeoIPEntry], output_dir: str, clean: bool = True) -> None:
    if clean and os.path.isdir(output_dir):
        shutil.rmtree(output_dir)

    os.makedirs(output_dir, exist_ok=True)

    for entry in entries:
        if not entry.country_code:
            continue

        filename = safe_filename(entry.country_code) + ".list"
        output_path = os.path.join(output_dir, filename)

        rules = []
        for cidr in entry.cidrs:
            try:
                rules.append(cidr_to_shadowrocket_rule(cidr))
            except ValueError:
                continue

        rules = sorted(set(rules))

        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# {entry.country_code}\n")
            f.write(f"# Converted from geoip.dat for Shadowrocket\n")
            for rule in rules:
                f.write(rule + "\n")

        print(f"Generated {output_path}: {len(rules)} rules")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert v2ray geoip.dat to Shadowrocket IP ruleset"
    )
    parser.add_argument(
        "-i",
        "--input",
        default="geoip.dat",
        help="Path to geoip.dat, default: geoip.dat",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="rules-ip",
        help="Output directory, default: rules-ip",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not clean output directory before generating",
    )

    args = parser.parse_args()

    with open(args.input, "rb") as f:
        data = f.read()

    entries = parse_geoip_list(data)
    write_rules(entries, args.output, clean=not args.no_clean)

    print(f"Done. Generated {len(entries)} geoip rule files in {args.output}/")


if __name__ == "__main__":
    main()
