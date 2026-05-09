import tempfile
import unittest
from pathlib import Path

from scripts.geosite_to_shadowrocket import (
    DOMAIN_DOMAIN,
    DOMAIN_FULL,
    DOMAIN_PLAIN,
    DOMAIN_REGEX,
    parse_geosite_list,
    shadowrocket_lines,
    write_rulesets,
)


def varint(value):
    chunks = []
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            chunks.append(byte | 0x80)
        else:
            chunks.append(byte)
            return bytes(chunks)


def field_varint(number, value):
    return varint((number << 3) | 0) + varint(value)


def field_bytes(number, value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return varint((number << 3) | 2) + varint(len(value)) + value


def domain(domain_type, value):
    return field_varint(1, domain_type) + field_bytes(2, value)


def geosite(code, domains):
    payload = field_bytes(1, code)
    for item in domains:
        payload += field_bytes(2, item)
    return payload


class GeositeToShadowrocketTest(unittest.TestCase):
    def test_parse_and_convert_supported_domain_types(self):
        data = field_bytes(
            1,
            geosite(
                "TEST-SET",
                [
                    domain(DOMAIN_PLAIN, "keyword"),
                    domain(DOMAIN_REGEX, "^example\\.com$"),
                    domain(DOMAIN_DOMAIN, "example.com"),
                    domain(DOMAIN_FULL, "full.example.com"),
                ],
            ),
        )

        sites = parse_geosite_list(data)

        self.assertEqual(sites[0].code, "TEST-SET")
        self.assertEqual(
            shadowrocket_lines(sites[0]),
            [
                "DOMAIN-KEYWORD,keyword",
                "DOMAIN-REGEX,^example\\.com$",
                "DOMAIN-SUFFIX,example.com",
                "DOMAIN,full.example.com",
            ],
        )

    def test_write_rulesets_uses_lowercase_ruleset_name(self):
        data = field_bytes(
            1,
            geosite("GEOLOCATION-CN", [domain(DOMAIN_DOMAIN, "example.cn")]),
        )
        sites = parse_geosite_list(data)

        with tempfile.TemporaryDirectory() as temp_dir:
            count = write_rulesets(sites, Path(temp_dir), ".list")
            output = Path(temp_dir) / "geolocation-cn.list"

            self.assertEqual(count, 1)
            self.assertEqual(output.read_text(), "DOMAIN-SUFFIX,example.cn\n")


if __name__ == "__main__":
    unittest.main()
