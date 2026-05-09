#!/usr/bin/env python3
"""Download and convert v2ray geosite.dat into Shadowrocket rule-set files.

The geosite.dat file is a protobuf-encoded GeoSiteList.  This script uses a
small protobuf wire-format reader so the scheduled workflow does not need any
third-party Python packages.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_URL = "https://raw.githubusercontent.com/Loyalsoldier/v2ray-rules-dat/release/geosite.dat"
DEFAULT_OUTPUT_DIR = "rules"

# v2ray-domain-list-community domain types used in geosite.dat.
DOMAIN_PLAIN = 0
DOMAIN_REGEX = 1
DOMAIN_DOMAIN = 2
DOMAIN_FULL = 3

SHADOWROCKET_RULE_TYPES = {
    DOMAIN_PLAIN: "DOMAIN-KEYWORD",
    DOMAIN_REGEX: "DOMAIN-REGEX",
    DOMAIN_DOMAIN: "DOMAIN-SUFFIX",
    DOMAIN_FULL: "DOMAIN",
}

_FILENAME_SAFE = re.compile(r"[^a-z0-9._!-]+")


@dataclass(frozen=True)
class Domain:
    type: int
    value: str


@dataclass(frozen=True)
class GeoSite:
    code: str
    domains: tuple[Domain, ...]


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


def parse_domain(data: bytes) -> Domain:
    reader = ProtoReader(data)
    domain_type = DOMAIN_PLAIN
    value = ""

    while not reader.eof():
        field, wire_type = reader.read_key()
        if field == 1 and wire_type == 0:
            domain_type = reader.read_varint()
        elif field == 2 and wire_type == 2:
            value = reader.read_bytes().decode("utf-8")
        else:
            reader.skip(wire_type)

    return Domain(type=domain_type, value=value)


def parse_geosite(data: bytes) -> GeoSite:
    reader = ProtoReader(data)
    code = ""
    domains: list[Domain] = []

    while not reader.eof():
        field, wire_type = reader.read_key()
        if field == 1 and wire_type == 2:
            code = reader.read_bytes().decode("utf-8")
        elif field == 2 and wire_type == 2:
            domain = parse_domain(reader.read_bytes())
            if domain.value:
                domains.append(domain)
        else:
            reader.skip(wire_type)

    return GeoSite(code=code, domains=tuple(domains))


def parse_geosite_list(data: bytes) -> list[GeoSite]:
    reader = ProtoReader(data)
    sites: list[GeoSite] = []

    while not reader.eof():
        field, wire_type = reader.read_key()
        if field == 1 and wire_type == 2:
            site = parse_geosite(reader.read_bytes())
            if site.code:
                sites.append(site)
        else:
            reader.skip(wire_type)

    return sites


def shadowrocket_lines(site: GeoSite) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()

    for domain in site.domains:
        rule_type = SHADOWROCKET_RULE_TYPES.get(domain.type)
        if rule_type is None:
            continue
        line = f"{rule_type},{domain.value}"
        if line not in seen:
            seen.add(line)
            lines.append(line)

    return lines


def normalize_ruleset_name(code: str) -> str:
    normalized = _FILENAME_SAFE.sub("_", code.strip().lower()).strip(".-_")
    if not normalized:
        raise ValueError(f"invalid geosite code for filename: {code!r}")
    return normalized


def write_rulesets(sites: Iterable[GeoSite], output_dir: Path, extension: str) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    if extension:
        for stale_file in output_dir.glob(f"*{extension}"):
            stale_file.unlink()

    count = 0

    for site in sites:
        ruleset_name = normalize_ruleset_name(site.code)
        path = output_dir / f"{ruleset_name}{extension}"
        lines = shadowrocket_lines(site)
        content = "\n".join(lines)
        if content:
            content += "\n"
        path.write_text(content, encoding="utf-8", newline="\n")
        count += 1

    return count


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "ruleset-geosite-converter"})
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())


def load_geosite_dat(args: argparse.Namespace) -> bytes:
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
        description="Convert v2ray geosite.dat into Shadowrocket rule-set files."
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("GEOSITE_DAT_URL", DEFAULT_URL),
        help=f"geosite.dat URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--input",
        help="read a local geosite.dat file instead of downloading one",
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
    data = load_geosite_dat(args)
    sites = parse_geosite_list(data)
    count = write_rulesets(sites, Path(args.output_dir), args.extension)
    print(f"Generated {count} Shadowrocket rule-set files in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
