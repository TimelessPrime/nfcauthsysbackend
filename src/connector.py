import json
import socket

# Import config.py to get get_host and get_server_port module
from config import get_host, get_server_port

HOST = get_host
PORT = get_server_port
BUFFER_SIZE = 4096


sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

sock.bind((HOST,PORT))

sock.listen(2)

print(f"Server listening on {HOST}:{PORT}")
class ClientHandler:
    def __init__(self, client:socket.socket):
        self.client = client
        self.buffer = b""
    def receive_data(self):
        try:
            # Nhan du lieu tu client
            packet = self.client.recv(BUFFER_SIZE)

            if not packet:
                print("Client Disconected!")
                return False

            self.buffer += packet
            return True
        except Exception as e:  # noqa: BLE001
            print(f"Error when recieve data: {e}")
            return None
    def extract_messages(self):

        tmp_json = []

        while b"\n" in self.buffer:
            try:

                line, self.buffer = self.buffer.split(b"\n", 1)
                try: 
                    text = json.loads(line.decode("UTF-8"))
                    vaildUTF = True
                except UnicodeDecodeError as e:
                    print(f"Error When Decode Unicode: {e}")
                    continue
                try: 
                    raw_json = json.loads(text)
                    vaildJSON = True
                except json.JSONDecodeError as e:
                    print(f"Invailed JSON: {e}")
                    continue

                if (vaildJSON) and (vaildUTF) == True:
                    continue
                tmp_json.append(raw_json)
            except json.JSONDecodeError as e:
                print(f"Erorr When Decoding JSON: {e}")

        return tmp_json




