import unittest
from types import SimpleNamespace
from unittest.mock import patch

import dns.resolver

from bot.checks.dns import _resolve_dns_snapshot_sync


class FakeResolver:
    def __init__(self):
        self.lifetime = None
        self.calls = []

    def resolve(self, name, record_type):
        self.calls.append((name, record_type))
        if record_type == "NS" and name == "api.example.com":
            raise dns.resolver.NoAnswer()
        if record_type == "NS":
            return [
                SimpleNamespace(target="NS2.EXAMPLE.NET."),
                SimpleNamespace(target="ns1.example.net."),
            ]
        return [
            SimpleNamespace(preference=20, exchange="MX2.EXAMPLE.NET."),
            SimpleNamespace(preference=10, exchange="mx1.example.net."),
        ]


class DnsSnapshotTest(unittest.TestCase):
    def test_resolves_authoritative_parent_and_normalizes_values(self):
        resolver = FakeResolver()
        with patch("bot.checks.dns.dns.resolver.Resolver", return_value=resolver):
            snapshot = _resolve_dns_snapshot_sync(
                "https://api.example.com",
                ["2001:4860:4860::8888", "8.8.8.8", "8.8.8.8"],
                4,
            )

        self.assertEqual(snapshot["ips"], ["2001:4860:4860::8888", "8.8.8.8"])
        self.assertEqual(snapshot["ns"], ["ns1.example.net", "ns2.example.net"])
        self.assertEqual(
            snapshot["mx"],
            ["10 mx1.example.net", "20 mx2.example.net"],
        )
        self.assertEqual(resolver.lifetime, 4)
        self.assertEqual(
            resolver.calls,
            [
                ("api.example.com", "NS"),
                ("example.com", "NS"),
                ("example.com", "MX"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
