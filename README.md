# Shadowrocket rulesets

This repository generates Shadowrocket-compatible rule-set files from
[`Loyalsoldier/v2ray-rules-dat`](https://github.com/Loyalsoldier/v2ray-rules-dat/tree/release)'s
`geosite.dat` and `geoip.dat` release artifacts.

## Update schedule

The GitHub Actions workflow runs every day at **00:00 UTC**, downloads the latest
`geosite.dat` and `geoip.dat` from the `release` branch, then writes generated
Shadowrocket rule-set files into:

- `rules/` for domain rule sets converted from `geosite.dat`
- `rules-ip/` for IP rule sets converted from `geoip.dat`

## File naming

Generated files use the original geosite or geoip rule-set name as their base
name.

For example:

- `geosite:geolocation-cn` is written to `rules/geolocation-cn.list`
- `geoip:cn` is written to `rules-ip/cn.list`

## Domain rule conversion

The converter maps v2ray geosite domain types to Shadowrocket rule types as
follows:

| geosite type | Shadowrocket rule |
| --- | --- |
| `Plain` | `DOMAIN-KEYWORD` |
| `Regex` | `DOMAIN-REGEX` |
| `Domain` | `DOMAIN-SUFFIX` |
| `Full` | `DOMAIN` |

## IP rule conversion

The converter maps every IPv4 and IPv6 CIDR in `geoip.dat` to Shadowrocket's
unified `IP-CIDR` rule type:

```text
IP-CIDR,1.2.3.0/24
IP-CIDR,2001:db8::/32
