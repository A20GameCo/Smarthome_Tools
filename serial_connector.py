from network_connector import NetworkConnector, Request
from typing import Optional
import serial
import re
import time
import json


class SerialConnector(NetworkConnector):
    """Class to implement a MQTT connection module"""

    __client: serial.Serial
    __own_name: str
    __baud_rate: int
    __port: str

    def __init__(self, own_name: str, port: str, baudrate: int):
        self.__own_name = own_name
        self.__baud_rate = baudrate
        self.__port = port
        self.__client = serial.Serial(port=self.__port, baudrate=self.__baud_rate, timeout=1)

    def __del__(self):
        pass

    def send_request(self, req: Request) -> (Optional[bool], Optional[Request]):
        """Sends a request on the serial port and waits for the answer"""

        self.send_serial(req)
        timeout_time = time.time() + 6
        while time.time() < timeout_time:
            remaining_time = timeout_time - time.time()
            res = self.read_serial(2 if remaining_time > 2 else remaining_time)
            if res and res.get_session_id() == req.get_session_id():
                res_ack = res.get_ack()
                res_status_msg = res.get_status_msg()
                if res_status_msg is None:
                    res_status_msg = "no status message received"
                return res_ack, res_status_msg, res
        return None, "no response received", None

    def decode_line(self, line) -> Optional[Request]:
        """Decodes a line and extracts a request if there is any"""

        if line[:3] == "!r_":
            elems = re.findall("_([a-z])\[(.+?)\]", line)
            req_dict = {}
            for elem_type, val in elems:
                if elem_type in req_dict:
                    print("Double key in request: '{}'".format(elem_type))
                    return None
                else:
                    req_dict[elem_type] = val
            for key in ["p", "b"]:
                if key not in req_dict:
                    print("Missig key in request: '{}'".format(key))
                    return None
            try:
                json_body = json.loads(req_dict["b"])

                out_req = Request(path=req_dict["p"],
                                  session_id=json_body["session_id"],
                                  sender=json_body["sender"],
                                  receiver=json_body["receiver"],
                                  payload=json_body["payload"])

                return out_req
            except ValueError:
                return None
        return None

    def send_serial(self, req: Request) -> bool:
        """Sends a request on the serial port"""

        req_line = "!r_p[{}]_b[{}]_\n".format(req.get_path(),
                                              str(req.get_body()).replace("'", '"').replace("None", "null"))
        # print("Sending '{}'".format(req_line[:-1]))
        self.__client.write(req_line.encode())
        return True

    def read_serial(self, timeout: int = 0, monitor_mode: bool = False) -> Optional[Request]:
        """Tries to read a line from the serial port"""

        timeout_time = time.time() + timeout
        while True:
            try:
                ser_bytes = self.__client.readline().decode()
                # if ser_bytes.startswith("!"):
                # print("   -> {}".format(ser_bytes[:-1]))
                if monitor_mode:
                    print(ser_bytes[:-1])
                else:
                    if ser_bytes.startswith("Backtrace: 0x"):
                        print("Client crashed with {}".format(ser_bytes[:-1]))
                        return None
                    read_buf_req = self.decode_line(ser_bytes)
                    if read_buf_req:
                        return read_buf_req
            except (FileNotFoundError, serial.serialutil.SerialException):
                print("Lost connection to serial port")
                return None
            if (timeout > 0) and (time.time() > timeout_time):
                return None

    def send_broadcast(self, req: Request, timeout: int = 5, responses_awaited: int = 0) -> [Request]:
        """Sends a broadcast and waits for answers"""
        responses: [Request] = []

        self.send_serial(req)
        timeout_time = time.time() + timeout
        while time.time() < timeout_time:
            remaining_time = timeout_time - time.time()
            incoming_req = self.read_serial(2 if remaining_time > 2 else remaining_time)
            if incoming_req and incoming_req.get_path() == "smarthome/broadcast/res" and incoming_req.get_session_id() == req.get_session_id():
                responses.append(incoming_req)
                if 0 < responses_awaited <= len(responses):
                    return responses
        return responses


if __name__ == '__main__':
    mqtt_gadget = SerialConnector("TesTeR", "192.168.178.111", 1883)

    buf_req = Request("smarthome/debug",
                      125543,
                      "me",
                      "you",
                      {"yolo": "blub"})

    mqtt_gadget.send_request(buf_req)
