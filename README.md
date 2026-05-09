# Shadowrocket geosite rulesets

This repository generates Shadowrocket-compatible rule-set files from
[`Loyalsoldier/v2ray-rules-dat`](https://github.com/Loyalsoldier/v2ray-rules-dat/tree/release)'s
`geosite.dat` release artifact.

## Update schedule

The GitHub Actions workflow runs every day at **00:30 UTC**, downloads the latest `geosite.dat` from the `release`
branch, splits every geosite entry, and writes one Shadowrocket rule-set file per
entry into `rules/`.

## File naming

Generated files use the geosite rule-set name as their base name. For
example, the `geolocation-cn` geosite entry is written to
`rules/geolocation-cn.list`.

## Rule conversion

The converter maps v2ray geosite domain types to Shadowrocket rule types as
follows:

| geosite type | Shadowrocket rule |
| --- | --- |
| `Plain` | `DOMAIN-KEYWORD` |
| `Regex` | `DOMAIN-REGEX` |
| `Domain` | `DOMAIN-SUFFIX` |
| `Full` | `DOMAIN` |

## Manual generation

```bash
python scripts/geosite_to_shadowrocket.py
```

To convert a local `geosite.dat` file instead of downloading one:

```bash
python scripts/geosite_to_shadowrocket.py --input /path/to/geosite.dat
```
