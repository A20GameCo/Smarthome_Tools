import serial
import time
import argparse
import json
import re
import socket
import random
import os
import sys
from typing import Union, Optional
from pprint import pprint

NETWORK_MODES = ["serial", "mqtt"]
CONFIG_ATTRIBUTES = ["id", "wifi_ssid", "wifi_pw", "mqtt_ip", "mqtt_port", "mqtt_user", "mqtt_pw"]

parser = argparse.ArgumentParser(description='Script to upload configs to the controller')

# network mode
parser.add_argument("--network_mode", help="may either be 'serial' or 'mqtt'")

# serial settings
parser.add_argument('--port', help='serial port to connect to.')
parser.add_argument('--baudrate', help='baudrate for the serial connection.')

# config file
parser.add_argument('--config_file', help='path to the config that should be uploaded.')

# individual data
parser.add_argument('--wifi_id', help='id to be uploaded.')
parser.add_argument('--wifi_ssid', help='ssid to be uploaded.')
parser.add_argument('--wifi_pw', help='password to be uploaded.')
parser.add_argument('--mqtt_ip', help='mqtt ip to be uploaded.')
parser.add_argument('--mqtt_port', help='port to be uploaded.')
parser.add_argument('--mqtt_user', help='mqtt username to be uploaded.')
parser.add_argument('--mqtt_pw', help='mqtt password to be uploaded.')

parser.add_argument('--network_only',
                    action='store_true',
                    help='needs a config file. uploads only the network config.')
parser.add_argument('--id_only',
                    action='store_true',
                    help='needs a config file. uploads only the id.')
parser.add_argument('--monitor_mode',
                    action='store_true',
                    help='only uses the script as a read-only serial monitor')
parser.add_argument('--arg_attributes_only',
                    action='store_true',
                    help='so not load any config and just upload attributes set as script ')
ARGS = parser.parse_args()


def gen_req_id() -> int:
    """Generates a random Request ID"""

    return random.randint(0, 1000000)


def decode_line(line) -> Optional[dict]:
    """Decodes a line and extracts a request if there is any"""

    if line[:3] == "!r_":
        elems = re.findall("_([a-z])\[(.+?)\]", line)
        req_dict = {}
        for type, val in elems:
            if type in req_dict:
                print("Double key in request: '{}'".format(type))
                return None
            else:
                req_dict[type] = val
        # pprint(req_dict)
        for key in ["p", "b"]:
            if key not in req_dict:
                print("Missig key in request: '{}'".format(key))
                return None
        try:
            json_body = json.loads(req_dict["b"])
            req_dict["b"] = json_body

            req_dict["path"] = req_dict["p"]
            req_dict["body"] = req_dict["b"]

            return req_dict
        except ValueError:
            return None
    return None


def send_serial(path: str, body: Union[dict, str]) -> bool:
    """Sends a request on the serial port"""

    if isinstance(body, dict):
        str_body = json.dumps(body)
    elif isinstance(body, str):
        str_body = body
    else:
        print("Body has illegal type")
        return False
    if not isinstance(path, str):
        print("Path has illegal type")
        return False
    req_line = "!r_p[{}]_b[{}]_\n".format(path, str_body)
    # print("Sending '{}'".format(req_line[:-1]))
    ser.write(req_line.encode())
    return True


def read_serial(timeout: int = 0, monitor_mode: bool = False) -> Union[bool, dict]:
    """Tries to read a line from the serial port"""

    timeout_time = time.time() + timeout
    while True:
        try:
            ser_bytes = ser.readline().decode()
            # if ser_bytes.startswith("!"):
            #     print("   -> {}".format(ser_bytes[:-1]))
            if monitor_mode:
                print(ser_bytes[:-1])
            else:
                if ser_bytes.startswith("Backtrace: 0x"):
                    print("Client crashed with {}".format(ser_bytes[:-1]))
                    return False
                buf_req = decode_line(ser_bytes)
                if buf_req:
                    return buf_req
        except (FileNotFoundError, serial.serialutil.SerialException):
            print("Lost connection to serial port")
            return False
        if (timeout > 0) and (time.time() > timeout_time):
            # print("Connection timed out")
            return False


def send_request(path: str, body: dict) -> bool:
    """Sends a request on the serial port and waits for the answer"""

    if "session_id" not in body:
        print("Cannot send request: body is missing id")
        return False
    req_id = body["session_id"]
    send_serial(path, body)
    timeout_time = time.time() + 6
    while time.time() < timeout_time:
        remaining_time = timeout_time - time.time()
        req = read_serial(2 if remaining_time > 2 else remaining_time)
        if req and "session_id" in req["body"] and req["body"]["session_id"] == req_id:
            if "ack" in req["body"]:
                return req["body"]["ack"]
            print("Received answer to request not containing 'ack'")
            return False
    return False


def do_broadcast() -> [str]:
    """Sends a broadcast and waits for clients to answer"""

    client_names = []
    session_id = gen_req_id()
    req = {}
    req["session_id"] = session_id
    send_serial("smarthome/broadcast/req", req)
    timeout_time = time.time() + 6
    while time.time() < timeout_time:
        remaining_time = timeout_time - time.time()
        req = read_serial(2 if remaining_time > 2 else remaining_time)
        if req and req["path"] == "smarthome/broadcast/res":
            if "chip_id" in req["body"] and "session_id" in req["body"] and req["body"]["session_id"] == session_id:
                if network_mode == 0:
                    return [req["body"]["chip_id"]]
                else:
                    client_names.append(req["body"]["chip_id"])
    return client_names


def config_args_existing() -> bool:
    """checks whether valid configs exist or not"""

    args_dict = vars(ARGS)
    for attr_name in CONFIG_ATTRIBUTES:
        if attr_name in args_dict and args_dict[attr_name] is not None:
            return True
    return False


def add_args_to_config(config: dict) -> dict:
    """Reads pre-set attributes from the ARGS into the config"""

    args_dict = vars(ARGS)
    for attr_name in CONFIG_ATTRIBUTES:
        if attr_name in args_dict and args_dict[attr_name] is not None:
            if config is None:
                config = {}
                config["name"] = "<args>"
                config["desciption"] = ""
                config["data"] = {}
            config["data"][attr_name] = args_dict[attr_name]
    return config


def select_option(input_list: [str], category: str = None) -> int:
    """Presents every elem from the list and lets the user select one"""

    if category is None:
        print("Please select:")
    else:
        print("Please select a {}:".format(category))
    for i in range(len(input_list)):
        print("    {}: {}".format(i, input_list[i]))
    var = None
    while var is None:
        var = input("Please select an option by entering its number:\n")
        try:
            var = int(var)
        except TypeError:
            var = None
        if var < 0 or var >= len(input_list):
            print("Illegal input, try again.")
            var = None
    return var


def load_config_file(f_name: str) -> Optional[dict]:
    """Loads a config from the disk if possible"""

    try:
        with open(os.path.join("configs", f_name)) as json_file:
            cfg_json = json.load(json_file)
            if "name" not in cfg_json:
                cfg_json["name"] = f_name
            if "description" not in cfg_json:
                cfg_json["description"] = ""
            return cfg_json
    except IOError:
        return None


def select_config() -> Optional[dict]:
    """Scans for valid configs and lets the user select ont if needed and possible"""

    config_files = [f_name for f_name in os.listdir("configs") if
                    os.path.isfile(os.path.join("configs", f_name)) and f_name.endswith(".json")]
    valid_configs = []
    config_names = []
    for f_name in config_files:
        config_json = load_config_file(f_name)
        if json is not None:
            valid_configs.append(config_json)
            config_names.append(config_json["name"])

    if len(config_names) == 0:
        return None
    if len(config_names) == 1:
        return valid_configs[0]

    cfg_i = select_option(config_names, "config")
    return valid_configs[cfg_i]


def connect_to_client() -> Optional[dict]:
    """Scans for clients and lets the user select one if needed and possible"""

    client_id = None

    print("Please make sure your chip can receive serial requests")
    client_list = do_broadcast()

    if len(client_list) == 0:
        print("No client answered to broadcast")
    elif len(client_list) > 1:
        print("Multiple clients answered to broadcast (wtf)")
    else:
        client_id = client_list[0]
        print("Connected to '{}'".format(client_id))
    return client_id


def load_config() -> Optional[dict]:
    """Loads a selected config and inserts possible ARGS parameters"""

    out_cfg = None
    if not ARGS.arg_attributes_only:
        if ARGS.config_file:
            out_cfg = load_config_file(ARGS.config_file)
        else:
            out_cfg = select_config()

    out_cfg = add_args_to_config(out_cfg)

    # Remove unknown attributes
    for attr in out_cfg["data"]:
        if attr not in CONFIG_ATTRIBUTES:
            print("Unknown attribute in config: '{}'".format(attr))
            out_cfg["data"].pop("attr")

    return out_cfg


if __name__ == '__main__':

    network_mode = None
    if ARGS.network_mode:
        if ARGS.network_mode == "serial":
            network_mode = 0
        elif ARGS.network_mode == "mqtt":
            network_mode = 1
        else:
            print("Gave illegal network mode '{}'".format(ARGS.network_mode == "mqtt"))
            network_mode = select_option(NETWORK_MODES, "network mode")
    else:
        network_mode = select_option(NETWORK_MODES, "network mode")

    print()

    if network_mode == 0:  # SERIAL MODE
        if ARGS.port:
            serial_port = ARGS.port
        else:
            serial_port = '/dev/cu.SLAB_USBtoUART'

        if ARGS.baudrate:
            serial_baudrate = ARGS.baudrate
        else:
            serial_baudrate = 115200

        serial_active = False
        try:
            ser = serial.Serial(port=serial_port, baudrate=serial_baudrate, timeout=1)
            ser.flushInput()
            serial_active = True
        except (FileNotFoundError, serial.serialutil.SerialException) as e:
            print("Unable to connect to serial port '{}'".format(serial_port))

        if serial_active:
            if ARGS.monitor_mode:
                read_serial(0, True)
                sys.exit(0)
        else:
            sys.exit(1)

    else:
        print("MQTT is currently not supported")
        sys.exit(1)

    CLIENT_NAME = connect_to_client()
    CONFIG_FILE = load_config()
    print()

    if CONFIG_FILE is None:
        print("No config could be loaded")
        sys.exit(1)
    else:
        print("Config '{}' was loaded".format(CONFIG_FILE["name"]))
    print()

    for attr in CONFIG_ATTRIBUTES:
        if attr in CONFIG_FILE["data"]:
            attr_data = CONFIG_FILE["data"][attr]
            req_dict = {"receiver": CLIENT_NAME, "param": attr, "value": attr_data,
                        "session_id": gen_req_id()}
            success = send_request("smarthome/config/write", req_dict)
            if success:
                print("[✓] Flashing '{}' was successful".format(attr))
                if attr == "id":
                    CLIENT_NAME = attr_data
            else:
                print("[×] Flashing '{}' failed".format(attr))

    if not ARGS.id_only and not ARGS.network_only:
        # upload gadgets
        pass