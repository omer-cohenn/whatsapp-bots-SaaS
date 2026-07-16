"""Port-exposure guard — in prod, only the reverse-proxy may publish host ports.

The production posture (docs/security/production-networking.md) is: exactly ONE
public door (the Caddy reverse-proxy on 80/443); postgres, redis, gateway,
backend and the static frontend stay on the internal network with no host
`ports:`. This guard parses infra/docker-compose.prod.yml and FAILS if any
service OTHER than `reverse-proxy` declares a published port — so a future edit
that re-exposes the backend or database trips CI instead of shipping.

It reads the OVERRIDE file on its own (a plain YAML parse), which is exactly
where port publishing is (re)declared for prod. Skips cleanly when the file
isn't present in the current environment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover - pyyaml is a dev/test dep
    yaml = None

# The single service allowed to publish host ports in production.
_PUBLIC_SERVICE = "reverse-proxy"


if yaml is not None:

    class _ComposeLoader(yaml.SafeLoader):
        """SafeLoader that tolerates Compose's merge tags (!override / !reset).

        The prod override uses `ports: !override []` to RESET (not append) ports.
        Plain safe_load rejects the unknown tag, so we resolve those tags to their
        underlying value (a bare `[]` / mapping / scalar), which is all this guard
        needs to read the declared ports.
        """

    def _resolve_compose_tag(loader, node):
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return loader.construct_scalar(node)

    for _tag in ("!override", "!reset"):
        _ComposeLoader.add_constructor(_tag, _resolve_compose_tag)


def _find_prod_compose() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "docker-compose.prod.yml"
        if candidate.is_file():
            return candidate
    return None


def _publishes_ports(service: dict) -> bool:
    """True if the service declares at least one published host port.

    Handles both compose port syntaxes:
      - short string  "80:80" / "127.0.0.1:80:80"  (a host mapping = published)
      - long mapping  {published: 80, target: 80}
    A bare container port like "8000" (no colon, no `published`) is NOT a host
    publish, so it doesn't count.
    """
    ports = service.get("ports")
    if not ports:
        return False
    for entry in ports:
        if isinstance(entry, dict):
            if entry.get("published") not in (None, ""):
                return True
        elif isinstance(entry, str):
            if ":" in entry:  # host:container mapping
                return True
        elif entry is not None:
            return True
    return False


def test_only_reverse_proxy_publishes_ports_in_prod():
    if yaml is None:
        pytest.skip("PyYAML not available")

    prod = _find_prod_compose()
    if prod is None:
        pytest.skip("infra/docker-compose.prod.yml not available in this environment")

    doc = yaml.load(prod.read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}
    services = doc.get("services", {})
    assert services, "prod compose override declares no services"

    offenders = [
        name
        for name, svc in services.items()
        if name != _PUBLIC_SERVICE and isinstance(svc, dict) and _publishes_ports(svc)
    ]
    assert not offenders, (
        "only the reverse-proxy may publish host ports in prod; these also do: "
        + ", ".join(sorted(offenders))
    )

    # And the proxy itself MUST publish (else the override is inert / misconfigured).
    proxy = services.get(_PUBLIC_SERVICE)
    assert proxy is not None, f"prod override is missing the {_PUBLIC_SERVICE} service"
    assert _publishes_ports(proxy), f"{_PUBLIC_SERVICE} must publish host ports (80/443)"
