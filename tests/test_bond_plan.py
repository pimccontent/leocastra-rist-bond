import unittest

from bond_plan import (
    bondable,
    iface_kind,
    local_srt_args,
    loopback_paths,
    parse_studio_urls,
    path_urls,
    receiver_args,
    recovery_window,
    ristsender_args,
    selected_paths,
)


NETS = [
    {"iface": "lo", "address": "127.0.0.1", "kind": "ignore"},
    {"iface": "enp3s0", "address": "192.168.0.20", "kind": "ethernet"},
    {"iface": "usb0", "address": "192.168.8.100", "kind": "uplink"},
    {"iface": "usb1", "address": "192.168.9.100", "kind": "uplink"},
    {"iface": "wlan0", "address": "", "kind": "uplink"},
]


class BondPlanTest(unittest.TestCase):
    def test_ethernet_is_lan_and_modems_bond(self):
        self.assertEqual(iface_kind("enp3s0"), "ethernet")
        self.assertEqual(iface_kind("usb0"), "uplink")
        self.assertFalse(bondable("ethernet"))
        self.assertTrue(bondable("uplink"))

    def test_auto_skips_ethernet_and_empty_wifi(self):
        paths = selected_paths(NETS, "auto", [])
        self.assertEqual([row["iface"] for row in paths], ["usb0", "usb1"])

    def test_manual_keeps_only_the_chosen_modem(self):
        paths = selected_paths(NETS, "manual", ["usb1", "enp3s0"])
        self.assertEqual([row["iface"] for row in paths], ["usb1"])

    def test_two_hundred_ms_stays_fixed(self):
        self.assertEqual(recovery_window(200), (200, 200, 25))
        self.assertEqual(recovery_window(2000), (200, 2000, 50))

    def test_seamless_urls_pin_each_modem(self):
        paths = selected_paths(NETS, "auto", [])
        urls = path_urls("studio.example", 18180, paths, 200, "seamless", "", 0)
        self.assertEqual(len(urls), 2)
        self.assertIn("rist://studio.example:18180?", urls[0])
        self.assertIn("miface=usb0", urls[0])
        self.assertIn("weight=0", urls[0])
        self.assertIn("miface=usb1", urls[1])
        self.assertIn(":18181?", urls[1])
        args = ristsender_args("ristsender", 15000, urls)
        self.assertEqual(args[1:5], ["-p", "1", "-v", "4"])
        self.assertEqual(args[args.index("-o") + 1].count("rist://"), 2)

    def test_split_uses_weight_and_aes(self):
        urls = path_urls("10.0.0.8", 18180, [{"iface": "usb0"}], 1000, "split", "studio-key", 256)
        self.assertIn("weight=5", urls[0])
        self.assertIn("aes-type=256", urls[0])
        self.assertIn("secret=studio-key", urls[0])
        self.assertIn("buffer-min=200", urls[0])
        self.assertIn("buffer-max=1000", urls[0])

    def test_loopback_bond_skips_interface_pin(self):
        urls = path_urls("127.0.0.1", 18180, loopback_paths(), 2000, "seamless", "", 0, pin_interface=False)
        self.assertEqual(len(urls), 2)
        self.assertNotIn("miface=", urls[0])
        self.assertIn("weight=0", urls[0])
        self.assertIn(":18181?", urls[1])
        join = receiver_args("ristreceiver", 18180, 2, 2000, 6000)
        self.assertEqual(join[join.index("-i") + 1].count("rist://@0.0.0.0:"), 2)
        self.assertIn("udp://0.0.0.0:6000", join)

    def test_pasted_leocastra_lines_keep_one_host_and_both_ports(self):
        parsed = parse_studio_urls(
            "rist://studio.example:18180?buffer-min=200&buffer-max=2000&reorder-buffer=50&cname=leocastra\n"
            "rist://studio.example:18181?buffer-min=200&buffer-max=2000&aes-type=128&secret=studio-key\n"
        )
        self.assertEqual(parsed["studioHost"], "studio.example")
        self.assertEqual(parsed["studioPorts"], [18180, 18181])
        self.assertEqual(parsed["bufferMs"], 2000)
        self.assertEqual(parsed["encryption"], 128)
        urls = path_urls(
            parsed["studioHost"],
            parsed["basePort"],
            [{"iface": "usb0"}, {"iface": "usb1"}],
            parsed["bufferMs"],
            "seamless",
            parsed["secret"],
            parsed["encryption"],
            ports=parsed["studioPorts"],
        )
        self.assertIn("rist://studio.example:18180?", urls[0])
        self.assertIn(":18181?", urls[1])
        self.assertIn("miface=usb0", urls[0])
        self.assertIn("miface=usb1", urls[1])
        self.assertIn("session-timeout=10000", urls[0])

    def test_pasted_lines_must_match_the_modem_count(self):
        with self.assertRaises(ValueError):
            path_urls("studio.example", 18180, [{"iface": "usb0"}], 2000, "seamless", "", 0, ports=[18180, 18181])

    def test_local_encoder_is_srt_copy(self):
        args = local_srt_args("ffmpeg", 4011, 15000)
        self.assertIn("srt://0.0.0.0:4011?mode=listener&latency=200000&pkt_size=1316", args)
        self.assertIn("udp://127.0.0.1:15000?pkt_size=1316", args)


if __name__ == "__main__":
    unittest.main()
