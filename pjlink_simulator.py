import socket
import threading
import logging
import os
import json

# 設定終端機日誌輸出格式
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(name)s] - %(message)s')

class PJLinkSimulator:
    def __init__(self, port=4352, name="MockProjector"):
        self.port = port
        self.name = name
        self.logger = logging.getLogger(self.name)
        
        # PJLink 設備的內部狀態
        self.state = {
            "POWR": "0",       # 0: 關機, 1: 開機
            "INPT": "11",      # 11: RGB 1, 31: HDMI 1
            "AVMT": "30",      # 30: 影音皆無靜音, 31: 影音皆靜音
            "ERST": "000000",  # 錯誤狀態 (風扇/燈泡/溫度/上蓋/濾網/其他), 0=正常, 2=錯誤
            "LAMP": "1250",    # 燈泡累積時數
            "NAME": self.name, # 設備名稱
            "INF1": "MockVendor", # 廠牌
            "INF2": "BeamDeck-Mock-X1" # 型號
        }
        
        # 狀態儲存檔案，實現重啟後記憶
        self.state_file = f"{self.name}_state.json"
        self.load_state()

    def load_state(self):
        """從 JSON 檔案載入內部狀態"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    saved_state = json.load(f)
                    self.state.update(saved_state)
                    self.logger.info("已載入歷史狀態記錄。")
            except Exception as e:
                self.logger.error(f"讀取狀態失敗: {e}")

    def save_state(self):
        """將內部狀態儲存至 JSON 檔案"""
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=4)
        except Exception as e:
            self.logger.error(f"儲存狀態失敗: {e}")

    def handle_client(self, conn, addr):
        self.logger.info(f"建立連線: {addr}")
        # PJLink 握手協定 (0 表示不需要密碼認證)
        conn.sendall(b"PJLINK 0\r")
        
        try:
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                
                # PJLink 指令通常以 \r 結尾
                cmd_line = data.decode('utf-8').strip()
                self.logger.info(f"收到指令: {cmd_line}")
                
                response = self.process_command(cmd_line)
                if response:
                    conn.sendall(f"{response}\r".encode('utf-8'))
                    self.logger.info(f"回傳狀態: {response}")
                    
        except Exception as e:
            self.logger.error(f"通訊錯誤: {e}")
        finally:
            conn.close()

    def process_command(self, cmd_line):
        """解析與處理 PJLink 指令"""
        # 檢查是否符合 "%1COMMAND PARAM" 格式
        if not cmd_line.startswith("%1") or len(cmd_line) < 6:
            return "%1ERR4" # 無效的投影機指令
            
        cmd = cmd_line[2:6]
        param = cmd_line[7:] if len(cmd_line) > 6 else ""
        
        if cmd in self.state:
            if param == "?":
                # 【讀取】狀態
                # LAMP 指令比較特別，需要回傳時數與是否點亮的狀態
                if cmd == "LAMP":
                    lamp_on = "1" if self.state["POWR"] == "1" else "0"
                    return f"%1{cmd}={self.state['LAMP']} {lamp_on}"
                return f"%1{cmd}={self.state[cmd]}"
            else:
                # 【設定】狀態
                # 攔截唯讀屬性 (不允許透過網路修改設備名稱、錯誤碼等)
                readonly_cmds = ["ERST", "LAMP", "NAME", "INF1", "INF2"]
                if cmd in readonly_cmds:
                    return f"%1{cmd}=ERR3" # Unavailable time / 唯讀
                    
                # 更新狀態並存檔
                self.state[cmd] = param
                self.save_state()
                return f"%1{cmd}=OK"
        else:
            return "%1ERR3" # 不支援的指令

    def start(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', self.port))
        server.listen(5)
        self.logger.info(f"智慧 PJLink 模擬器啟動於 Port {self.port}...")
        
        while True:
            conn, addr = server.accept()
            thread = threading.Thread(target=self.handle_client, args=(conn, addr))
            thread.start()

if __name__ == "__main__":
    # 支援透過環境變數自訂 Port 與名稱，方便開多台
    port = int(os.environ.get('PJLINK_PORT', 4352))
    name = os.environ.get('PJLINK_NAME', 'Projector_A')
    sim = PJLinkSimulator(port=port, name=name)
    sim.start()