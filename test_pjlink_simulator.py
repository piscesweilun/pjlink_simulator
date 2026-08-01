import json
import os
import socket
import tempfile
import threading
import unittest

from pjlink_simulator import PJLinkSimulator


class PJLinkSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.simulator = PJLinkSimulator(
            name="TestProjector",
            state_dir=self.temp_dir.name,
            mac_address="02:11:22:33:44:55",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_advertises_class_2(self):
        self.assertEqual(self.simulator.process_command("%1CLSS ?"), "%1CLSS=2")

    def test_class_2_queries(self):
        expected = {
            "%2SNUM ?": "%2SNUM=SIM-TestProjector",
            "%2SVER ?": "%2SVER=2.10",
            "%2INNM ?31": "%2INNM=HDMI 1",
            "%2IRES ?": "%2IRES=1920x1080",
            "%2RRES ?": "%2RRES=1920x1080",
            "%2FILT ?": "%2FILT=0",
            "%2RLMP ?": "%2RLMP=MockLamp-X2",
            "%2RFIL ?": "%2RFIL=MockFilter-X2",
            "%2FREZ ?": "%2FREZ=0",
        }
        for command, response in expected.items():
            with self.subTest(command=command):
                self.assertEqual(self.simulator.process_command(command), response)

    def test_class_2_input_and_freeze_controls(self):
        self.assertEqual(self.simulator.process_command("%2INPT 6A"), "%2INPT=OK")
        self.assertEqual(self.simulator.process_command("%2INPT ?"), "%2INPT=6A")
        self.assertEqual(self.simulator.process_command("%2FREZ 1"), "%2FREZ=OK")
        self.assertEqual(self.simulator.process_command("%2FREZ ?"), "%2FREZ=1")

        with open(self.simulator.state_file, encoding="utf-8") as state_file:
            saved = json.load(state_file)
        self.assertEqual(saved["INPT"], "6A")
        self.assertEqual(saved["FREZ"], "1")

    def test_class_1_rejects_class_2_input_identifier(self):
        self.assertEqual(self.simulator.process_command("%1INPT 6A"), "%1INPT=ERR2")
        self.assertNotIn("6A", self.simulator.process_command("%1INST ?"))
        self.assertIn("6A", self.simulator.process_command("%2INST ?"))

    def test_volume_commands_and_validation(self):
        self.assertEqual(self.simulator.process_command("%2SVOL 1"), "%2SVOL=OK")
        self.assertEqual(self.simulator.state["SPEAKER_VOLUME"], 51)
        self.assertEqual(self.simulator.process_command("%2MVOL 0"), "%2MVOL=OK")
        self.assertEqual(self.simulator.state["MIC_VOLUME"], 49)
        self.assertEqual(self.simulator.process_command("%2FREZ 2"), "%2FREZ=ERR2")
        self.assertEqual(self.simulator.process_command("%2NOPE ?"), "%2NOPE=ERR1")

    def test_discovery_response(self):
        self.assertEqual(
            self.simulator.process_search_datagram(b"%2SRCH\r"),
            b"%2ACKN=02:11:22:33:44:55\r",
        )
        self.assertIsNone(self.simulator.process_search_datagram(b"%2SRCH\n"))

    def test_tcp_handler_supports_fragmented_and_multiple_commands(self):
        server_socket, client_socket = socket.socketpair()
        thread = threading.Thread(
            target=self.simulator.handle_client,
            args=(server_socket, ("local", 0)),
        )
        thread.start()
        self.assertEqual(client_socket.recv(64), b"PJLINK 0\r")

        client_socket.sendall(b"%1CL")
        client_socket.sendall(b"SS ?\r%2FREZ ?\r")
        received = b""
        while received.count(b"\r") < 2:
            received += client_socket.recv(128)
        self.assertEqual(received, b"%1CLSS=2\r%2FREZ=0\r")

        client_socket.close()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
