import hashlib
import json
import logging
import os
import random
import socket
import threading


logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(name)s] - %(message)s")


class PJLinkSimulator:
    """A small PJLink Class 2 projector/display simulator."""

    CLASS1_COMMANDS = {
        "POWR", "INPT", "AVMT", "ERST", "LAMP", "INST", "NAME",
        "INF1", "INF2", "INFO", "CLSS",
    }
    CLASS2_COMMANDS = {
        "INPT", "INST", "SNUM", "SVER", "INNM", "IRES", "RRES",
        "FILT", "RLMP", "RFIL", "SVOL", "MVOL", "FREZ",
    }
    READ_ONLY = {
        "ERST", "LAMP", "INST", "NAME", "INF1", "INF2", "INFO",
        "CLSS", "SNUM", "SVER", "INNM", "IRES", "RRES", "FILT",
        "RLMP", "RFIL",
    }

    def __init__(self, port=4352, name="MockProjector", state_dir=None,
                 mac_address=None, notify_host=None, notify_port=4352):
        self.port = port
        self.name = name
        self.logger = logging.getLogger(self.name)
        self._state_lock = threading.Lock()

        self.state = {
            "POWR": "0",
            "INPT": "31",
            "AVMT": "30",
            "ERST": "000000",
            "LAMP": "1250",
            "INST": "11 31 33 51 52 6A",
            "NAME": self.name,
            "INF1": "MockVendor",
            "INF2": "BeamDeck-Mock-X2",
            "INFO": "PJLink Class 2 Simulator",
            "CLSS": "2",
            "SNUM": f"SIM-{self.name}",
            "SVER": "2.10",
            "INPUT_NAMES": {
                "11": "RGB 1",
                "31": "HDMI 1",
                "33": "HDMI 3",
                "51": "Network 1",
                "52": "Network 2",
                "6A": "Internal A",
            },
            "IRES": "1920x1080",
            "RRES": "1920x1080",
            "FILT": "0",
            "RLMP": "MockLamp-X2",
            "RFIL": "MockFilter-X2",
            "FREZ": "0",
            "SPEAKER_VOLUME": 50,
            "MIC_VOLUME": 50,
        }

        state_dir = state_dir if state_dir is not None else os.environ.get("PJLINK_STATE_DIR", ".")
        self.state_file = os.path.join(state_dir, f"{self.name}_state.json")
        self.load_state()

        self.mac_address = (mac_address or os.environ.get("PJLINK_MAC") or
                            self._make_mac_address(self.name)).lower()
        self.notify_host = notify_host or os.environ.get("PJLINK_NOTIFY_HOST")
        self.notify_port = int(os.environ.get("PJLINK_NOTIFY_PORT", notify_port))
        self.search_delay_max = float(os.environ.get("PJLINK_SEARCH_DELAY_MAX", "10"))

    @staticmethod
    def _make_mac_address(name):
        digest = hashlib.sha256(name.encode("utf-8")).digest()
        # Locally administered, unicast MAC address.
        octets = bytes([0x02]) + digest[:5]
        return ":".join(f"{value:02x}" for value in octets)

    def load_state(self):
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as state_file:
                saved_state = json.load(state_file)
            self.state.update(saved_state)
            # A Class 2 simulator must always advertise Class 2.
            self.state["CLSS"] = "2"
            self.logger.info("已載入歷史狀態記錄。")
        except (OSError, ValueError, TypeError) as error:
            self.logger.error("讀取狀態失敗: %s", error)

    def save_state(self):
        try:
            state_dir = os.path.dirname(os.path.abspath(self.state_file))
            os.makedirs(state_dir, exist_ok=True)
            temporary_file = f"{self.state_file}.tmp"
            with open(temporary_file, "w", encoding="utf-8") as state_file:
                json.dump(self.state, state_file, indent=4, ensure_ascii=False)
            os.replace(temporary_file, self.state_file)
        except OSError as error:
            self.logger.error("儲存狀態失敗: %s", error)

    def handle_client(self, conn, addr):
        self.logger.info("建立 TCP 連線: %s", addr)
        conn.sendall(b"PJLINK 0\r")
        buffer = b""

        try:
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                buffer += data

                while b"\r" in buffer:
                    raw_line, buffer = buffer.split(b"\r", 1)
                    if not raw_line:
                        continue
                    try:
                        cmd_line = raw_line.decode("utf-8")
                    except UnicodeDecodeError:
                        self.logger.warning("忽略非 UTF-8 指令: %r", raw_line)
                        continue

                    self.logger.info("收到指令: %s", cmd_line)
                    response = self.process_command(cmd_line)
                    if response is not None:
                        conn.sendall(f"{response}\r".encode("utf-8"))
                        self.logger.info("回傳狀態: %s", response)

                # Header + class + command + space + max parameter + CR.
                if len(buffer) > 135:
                    self.logger.warning("捨棄過長的 PJLink 指令")
                    buffer = b""
        except (ConnectionError, OSError) as error:
            self.logger.error("TCP 通訊錯誤: %s", error)
        finally:
            conn.close()

    @staticmethod
    def _response(pjlink_class, command, value):
        return f"%{pjlink_class}{command}={value}"

    def process_command(self, cmd_line):
        """Parse one PJLink command without its terminating CR."""
        encoded = cmd_line.encode("utf-8")
        if len(encoded) > 134 or len(cmd_line) < 8:
            return None
        if cmd_line[0] != "%" or cmd_line[1] not in ("1", "2") or cmd_line[6] != " ":
            return None

        pjlink_class = cmd_line[1]
        command = cmd_line[2:6].upper()
        parameter = cmd_line[7:]
        supported = self.CLASS1_COMMANDS if pjlink_class == "1" else self.CLASS2_COMMANDS
        if command not in supported:
            return self._response(pjlink_class, command, "ERR1")

        if parameter.startswith("?"):
            return self._handle_query(pjlink_class, command, parameter)
        return self._handle_set(pjlink_class, command, parameter)

    def _handle_query(self, pjlink_class, command, parameter):
        if command == "INNM":
            input_number = parameter[1:]
            value = self.state["INPUT_NAMES"].get(input_number)
            if value is None or input_number not in self.state["INST"].split():
                value = "ERR2"
            return self._response(pjlink_class, command, value)

        if parameter != "?":
            return self._response(pjlink_class, command, "ERR2")
        if command in ("SVOL", "MVOL"):
            return self._response(pjlink_class, command, "ERR2")

        if command == "LAMP":
            lamp_on = "1" if self.state["POWR"] in ("1", "3") else "0"
            value = f"{self.state['LAMP']} {lamp_on}"
        elif command == "INST" and pjlink_class == "1":
            value = " ".join(source for source in self.state["INST"].split()
                             if source[0] in "12345" and source[1].isdigit())
        else:
            value = self.state[command]
        return self._response(pjlink_class, command, value)

    def _handle_set(self, pjlink_class, command, parameter):
        if command in self.READ_ONLY:
            return self._response(pjlink_class, command, "ERR2")

        if command == "POWR":
            valid = parameter in ("0", "1")
        elif command == "AVMT":
            valid = parameter in ("10", "11", "20", "21", "30", "31")
        elif command == "INPT":
            valid = parameter in self.state["INST"].split()
            if pjlink_class == "1":
                valid = valid and parameter[0] in "12345" and parameter[1].isdigit()
        elif command == "FREZ":
            valid = parameter in ("0", "1")
        elif command in ("SVOL", "MVOL"):
            valid = parameter in ("0", "1")
        else:
            valid = False

        if not valid:
            return self._response(pjlink_class, command, "ERR2")

        with self._state_lock:
            if command == "SVOL":
                delta = 1 if parameter == "1" else -1
                self.state["SPEAKER_VOLUME"] = max(0, min(100, self.state["SPEAKER_VOLUME"] + delta))
            elif command == "MVOL":
                delta = 1 if parameter == "1" else -1
                self.state["MIC_VOLUME"] = max(0, min(100, self.state["MIC_VOLUME"] + delta))
            else:
                self.state[command] = parameter
            self.save_state()

        if command in ("POWR", "INPT"):
            self.send_status_notification(command)
        return self._response(pjlink_class, command, "OK")

    def process_search_datagram(self, data):
        """Return the Class 2 discovery response for a valid search datagram."""
        if data == b"%2SRCH\r":
            return f"%2ACKN={self.mac_address}\r".encode("ascii")
        return None

    def _send_search_response(self, udp_socket, response, addr):
        try:
            udp_socket.sendto(response, addr)
            self.logger.info("回覆 UDP 搜尋: %s", addr)
        except OSError as error:
            self.logger.error("UDP 搜尋回覆失敗: %s", error)

    def serve_udp(self):
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp_socket.bind(("0.0.0.0", self.port))
        self.logger.info("PJLink Class 2 UDP 搜尋啟動於 Port %s", self.port)
        while True:
            data, addr = udp_socket.recvfrom(1024)
            response = self.process_search_datagram(data)
            if response is None:
                continue
            delay = random.uniform(0, max(0, self.search_delay_max))
            timer = threading.Timer(delay, self._send_search_response,
                                    args=(udp_socket, response, addr))
            timer.daemon = True
            timer.start()

    def send_status_notification(self, command="LKUP"):
        if not self.notify_host:
            return
        if command == "LKUP":
            value = self.mac_address
        elif command == "POWR":
            value = "1" if self.state["POWR"] in ("1", "3") else "0"
        elif command in ("INPT", "ERST"):
            value = self.state[command]
        else:
            return

        payload = f"%2{command}={value}\r".encode("utf-8")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
                udp_socket.sendto(payload, (self.notify_host, self.notify_port))
        except OSError as error:
            self.logger.error("UDP 狀態通知失敗: %s", error)

    def start(self):
        udp_thread = threading.Thread(target=self.serve_udp, daemon=True)
        udp_thread.start()

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", self.port))
        server.listen(5)
        self.logger.info("PJLink Class 2 模擬器啟動於 TCP Port %s", self.port)
        self.send_status_notification("LKUP")

        while True:
            conn, addr = server.accept()
            thread = threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True)
            thread.start()


if __name__ == "__main__":
    simulator = PJLinkSimulator(
        port=int(os.environ.get("PJLINK_PORT", "4352")),
        name=os.environ.get("PJLINK_NAME", "Projector_A"),
    )
    simulator.start()
