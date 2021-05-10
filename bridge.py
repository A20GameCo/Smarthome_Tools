import argparse
import json
import socket
import random
import sys
import os
import time
import config_functions
import threading
from datetime import datetime
from chip_flasher import get_serial_ports
from bridge_threads import *
from tools import system_tools, git_tools

from homekit_connector import HomeConnectorType, HomeKitConnector
from serial_connector import SerialConnector
from smarthomeclient import SmarthomeClient
from gadget import Gadget, GadgetIdentifier, CharacteristicIdentifier, CharacteristicUpdateStatus, Characteristic
from typing import Optional
from mqtt_connector import MQTTConnector
from request import Request
import client_control_methods


def get_connected_chip_id(network: SerialConnector, sender: str) -> Optional[str]:
    broadcast_req = Request(
        "smarthome/broadcast/req",
        gen_req_id(),
        sender,
        None,
        {}
    )

    responses = network.send_broadcast(broadcast_req, 5, 1)

    if responses:
        return responses[0].get_sender()
    return None


def gen_req_id() -> int:
    """Generates a random Request ID"""
    return random.randint(0, 1000000)


def get_sender() -> str:
    """Returns the name used as sender (local hostname)"""
    return socket.gethostname()


def check_dict_for_keys(check_dict: dict, key_list: [str]) -> bool:
    """Checks if all given keys are included in the dict"""
    for key in key_list:
        if key not in check_dict:
            return False
    return True


def fill_with_nones(check_dict: dict, key_list: [str]) -> dict:
    """Checks if every of the given keys are present and adds the missing keys with a None value"""
    buf_dict = check_dict
    for key in key_list:
        if key not in buf_dict:
            buf_dict[key] = None
    return buf_dict


class MainBridge:
    """Main Bridge for the Smarthome Environment"""

    # region ATTRIBUTES

    # Name of the bridge
    __bridge_name: str

    # Bridge software commit hash
    __sw_commit: Optional[str]

    # Bridge software commit branch
    __sw_branch: Optional[str]

    # Git version of the system
    __git_version: Optional[str]

    # Platformio version of the system
    __pio_version: Optional[str]

    # Python version of the system
    __python_version: Optional[str]

    # Pipenv version of the system
    __pipenv_version: Optional[str]

    # Time the bridge was launched
    __time_launched: datetime

    # MQTT
    __mqtt_port: int
    __mqtt_ip: str
    __mqtt_user: Optional[str]
    __mqtt_pw: Optional[str]

    # API
    __api_port: int
    __api_thread: Thread
    __ws_api_port: int

    __network_gadget: MQTTConnector
    __mqtt_callback_thread: Thread
    __received_requests: int

    __streaming_message_queue: [str]

    # Gadgets:
    __gadgets: [Gadget]

    # Clients
    __clients: [SmarthomeClient]

    # Connectors
    __connectors = []

    # thread lock
    __lock = None

    # Chip Flashing
    __chip_sw_flash_thread = None

    # Config Flashing
    __chip_config_flash_thread = None

    # endregion

    def __init__(self, bridge_name: str, mqtt_ip: str, mqtt_port: int,
                 mqtt_username: Optional[str], mqtt_pw: Optional[str]):
        print("Setting up Bridge...")

        # Setting bridge name
        self.__bridge_name = bridge_name

        # Setting counter for received requests to 0
        self.__received_requests = 0

        # Setting the value for the software commit hash
        self.__sw_commit = git_tools.get_git_commit_hash()

        # Setting the value for the software branch
        self.__sw_branch = git_tools.get_git_branch()

        print(f"Bridge is running on: {self.__sw_commit}\n{' '*22}{self.__sw_branch}")

        self.__git_version = system_tools.read_git_version()

        self.__pio_version = system_tools.read_pio_version()

        self.__python_version = system_tools.read_python_version()

        self.__pipenv_version = system_tools.read_pipenv_version()

        print(f"External tools: "
              f"Python: {self.__python_version}\n{' '*16}"
              f"Pipenv: {self.__pipenv_version}\n{' '*16}"
              f"Pipenv: {self.__pio_version}\n{' '*16}"
              f"Platformio: {self.__pio_version}\n{' '*16}"
              f"Git: {self.__git_version}")

        # Set launch time
        self.__time_launched = datetime.now()

        # MQTT
        self.__mqtt_ip = mqtt_ip
        self.__mqtt_port = mqtt_port
        self.__mqtt_user = mqtt_username
        self.__mqtt_pw = mqtt_pw

        # API
        self.__api_port = 0
        self.__ws_api_port = 0

        self.__clients = []
        self.__gadgets = []
        self.__connectors = []

        self.__streaming_message_queue = []

        print("Setting up Network...")
        self.__network_gadget = MQTTConnector(self.__bridge_name,
                                              self.__mqtt_ip,
                                              self.__mqtt_port,
                                              None,
                                              None)
        self.__mqtt_callback_thread = BridgeMQTTThread(parent=self,
                                                       connector=self.__network_gadget)
        self.__mqtt_callback_thread.start()

        self.__lock = threading.Lock()
        print("Ok.")

    def add_dummy_data(self):
        self.__add_client("dummy_client1",
                          1234567)
        self.add_gadget(Gadget("dummy_lamp",
                               GadgetIdentifier(1),
                               "dummy_client1",
                               1234567,
                               [
                                   Characteristic(CharacteristicIdentifier(1),
                                                  0,
                                                  1,
                                                  1,
                                                  1),
                                   Characteristic(CharacteristicIdentifier(3),
                                                  0,
                                                  100,
                                                  1,
                                                  35)
                               ]))
        # self.add_gadget(Gadget("dummy_fan",
        #                        GadgetIdentifier(3),
        #                        "dummy_client1",
        #                        1234567,
        #                        [
        #                            Characteristic(CharacteristicIdentifier(1),
        #                                           0,
        #                                           100,
        #                                           1,
        #                                           35),
        #                            Characteristic(CharacteristicIdentifier(2),
        #                                           0,
        #                                           100,
        #                                           33,
        #                                           66)
        #                        ]))
        self.__add_connector(HomeConnectorType(1), {"name": "test_connector1",
                                                    "ip": self.__mqtt_ip,
                                                    "port": self.__mqtt_port})

    def handle_request(self, req: Request):
        """Receives a request from the watcher Thread and handles it"""
        self.__received_requests += 1

        if req.get_receiver() != "<bridge>":
            return

        print("Received Request Nr. {}: {}".format(self.__received_requests + 1, req.get_path()))

        req_pl: dict = req.get_payload()

        # Check if the request was sent by any known client and report activity
        if req.get_path() == "smarthome/heartbeat":
            local_client = self.__get_or_create_client_from_request(req)
            if local_client.needs_update():
                self.__ask_for_update(local_client)

        # Check if the request was sent by any known client and report activity
        if req.get_path() == "smarthome/sync":

            local_client = self.__get_or_create_client_from_request(req)

            all_keys_existing = check_dict_for_keys(req_pl, ["runtime_id", "gadgets", "port_mapping", "boot_mode"])
            if not all_keys_existing:
                print("Request is missing keys")

            req_pl = fill_with_nones(req_pl, ["sw_uploaded", "sw_commit", "sw_branch"])

            if not isinstance(req_pl["gadgets"], list):
                print("Gadget config in sync response was no list")
                return

            print("Received sync data from '{}'".format(local_client.get_name()))

            updated_gadgets: [str] = []

            # Go over all gadgets and create or update them
            for list_gadget in req_pl["gadgets"]:

                # If a gadget fails, it fails. That's why theres a giant try block.
                try:
                    g_name = list_gadget["name"]
                    g_type = GadgetIdentifier(list_gadget["type"])
                    g_characteristics = []
                    for characteristic in list_gadget["characteristics"]:
                        # Create new characteristic
                        new_c = Characteristic(CharacteristicIdentifier(characteristic["type"]),
                                               characteristic["min"],
                                               characteristic["max"],
                                               characteristic["step"],
                                               characteristic["value"])
                        # Save it
                        g_characteristics.append(new_c)

                    # Get the gadget if there is already one in existence with the correct name
                    buf_gadget: Optional[Gadget] = self.get_gadget(g_name)
                    if buf_gadget is not None:
                        # Update existing gadget
                        print("Updating '{}'".format(buf_gadget.get_name()))
                        buf_gadget.update_gadget_info(g_type,
                                                      req.get_sender(),
                                                      req_pl["runtime_id"],
                                                      g_characteristics)
                    else:
                        # Create new gadget since there is no gadget with selected name
                        print("Creating new '{}'".format(g_name))
                        buf_gadget = Gadget(g_name,
                                            g_type,
                                            req.get_sender(),
                                            req_pl["runtime_id"],
                                            g_characteristics)
                        self.add_gadget(buf_gadget)

                    # Save name of gadget to skip deletion
                    updated_gadgets.append(buf_gadget.get_name())

                except KeyError as e:
                    print("Error syncing gadget:")
                    print(e)

            deleted_gadgets = 0

            for gadget in self.__gadgets:
                if gadget.get_host_client() == req.get_sender():
                    if gadget.get_name() not in updated_gadgets:
                        self.delete_gadget(gadget)
                        deleted_gadgets += 1

            print("Updated {} Gadgets".format(len(updated_gadgets)))
            print("Deleted {} Gadgets".format(deleted_gadgets))

            # Report update to client
            local_client.update_data(req_pl["sw_uploaded"], req_pl["sw_commit"],
                                     req_pl["sw_branch"], req_pl["port_mapping"],
                                     req_pl["boot_mode"])

            print("Update finished.")

            return

        # Receive gadget characteristic update from client
        if req.get_path() == "smarthome/remotes/gadget/update":
            if "name" not in req_pl:
                print("No name in characteristic update message")
                return

            if "characteristic" not in req_pl:
                print("No characteristic in characteristic update message")
                return

            if "value" not in req_pl:
                print("No value in characteristic update message")
                return

            print("Received update for characteristic '{}' from '{}'".format(req_pl["name"],
                                                                             req_pl["characteristic"]))

            self.update_characteristic_from_client(req_pl["name"],
                                                   CharacteristicIdentifier(req_pl["characteristic"]),
                                                   req_pl["value"])
            return

    def flash_software(self, branch: str = "master", serial_port: str = "/dev/cu.SLAB_USBtoUART") -> (bool, str):
        """Flashes the Smarthome_ESP32 software from the selected branch to the chip"""

        # Check if there is still a process running
        if self.__chip_sw_flash_thread and self.__chip_sw_flash_thread.is_alive():
            return False, "There is still a process running"

        # Check if Serial Port is existing
        if serial_port and serial_port not in self.get_serial_ports():
            return False, "Serial port is not existing"

        # Launch Thread
        self.__chip_sw_flash_thread = ChipSWFlasherThread(branch,
                                                          False,
                                                          serial_port,
                                                          self.add_streaming_message)
        self.__chip_sw_flash_thread.start()

        return True, "Flashing started."

    def write_config_to_network_chip(self, config: dict, client_name: str) -> (bool, str):
        """
        Launches a process writing a config to a client connected to the same network

        :param config: Config to write
        :param client_name: Client to receive new config
        :return: (Whether starting the writing process was successful), (Status message)
        """
        # Check if there is still a process running
        if self.__chip_config_flash_thread and self.__chip_config_flash_thread.is_alive():
            return False, "There is still a process running"

        # Check client name?

        buf_mqtt_gadget = MQTTConnector(
            self.get_bridge_name() + "config_upload_" + str(gen_req_id()),
            self.__mqtt_ip,
            self.__mqtt_port,
            self.__mqtt_user,
            self.__mqtt_pw)

        # Launch Thread
        self.__chip_config_flash_thread = ChipConfigFlasherThread(
            self.get_bridge_name(),
            buf_mqtt_gadget,
            config,
            client_name,
            self.add_streaming_message
        )
        self.__chip_config_flash_thread.start()

        return True, "Writing started."

    def write_config_to_chip(self, config: dict, serial_port: Optional[str]) -> (bool, str):
        """
        Writes the passed config to a client connected via USB

        :param config: Config to write to the chip
        :param serial_port: Serial Port to connect to
        :return: (Whether starting writing process worked), (Status Message)
        """
        if not serial_port:
            serial_port = "/dev/cu.SLAB_USBtoUART"

        # Check if there is still a process running
        if self.__chip_config_flash_thread and self.__chip_config_flash_thread.is_alive():
            return False, "There is still a process running"

        buf_serial_gadget = SerialConnector(
            self.get_bridge_name(),
            serial_port,
            115200
        )

        if not buf_serial_gadget.connected():
            return False, f"Could not connect to '{serial_port}'"

        # Get client name
        client_name = get_connected_chip_id(buf_serial_gadget, self.get_bridge_name())

        if not client_name:
            return False, "Could not connect to serial client"

        # Launch Thread
        self.__chip_config_flash_thread = ChipConfigFlasherThread(
            self.get_bridge_name(),
            buf_serial_gadget,
            config,
            client_name,
            self.add_streaming_message
        )
        self.__chip_config_flash_thread.start()

        return True, "Upload started."

    @staticmethod
    def write_config(config: dict) -> bool:
        """
        Saves a config file to the disk to be present between reboots

        :param config: Config to save
        :return: Whether saving was successful
        """
        return config_functions.write_config(config)

    @staticmethod
    def load_config_names() -> [str]:
        """
        Returns the names of all stored configs

        :return: The names of all stored configs
        """
        configs, config_names = config_functions.load_configs()
        return config_names

    @staticmethod
    def load_config(name: str) -> Optional[dict]:
        """
        Loads the selected config

        :param name: Name of the config to be loaded
        :return: Content of the config
        """
        configs, _ = config_functions.load_configs()
        for config in configs:
            if config["name"] == name:
                return config

    @staticmethod
    def get_serial_ports() -> [str]:
        """Returns all serial ports existing on the host system"""
        return get_serial_ports()

    # region BRIDGE DATA

    def get_bridge_name(self) -> str:
        """Sets the name for the bridge"""
        with self.__lock:
            return self.__bridge_name

    def get_time_launched(self) -> datetime:
        """Returns the time the bridge got started"""
        with self.__lock:
            return self.__time_launched

    def get_sw_commit(self) -> Optional[str]:
        """Returns the software commit hash of the bridge"""
        with self.__lock:
            return self.__sw_commit

    def get_sw_branch(self) -> Optional[str]:
        """Returns the software branch of the bridge"""
        with self.__lock:
            return self.__sw_branch

    def get_host_pio_version(self) -> Optional[str]:
        """Returns the platformio version found on the host machine"""
        with self.__lock:
            return self.__pio_version

    def get_host_python_version(self) -> Optional[str]:
        """Returns the python version found on the host machine"""
        with self.__lock:
            return self.__python_version

    def get_host_pipenv_version(self) -> Optional[str]:
        """Returns the pipenv version found on the host machine"""
        with self.__lock:
            return self.__pipenv_version

    def get_host_git_version(self) -> Optional[str]:
        """Returns the git version found on the host machine"""
        with self.__lock:
            return self.__git_version

    # endregion

    # region CLIENT METHODS

    def get_client(self, name: str) -> Optional[SmarthomeClient]:
        """
        Returns the client to the given name if it exists

        :param name: Name of the wanted client
        :return: The client object if found, None otherwise
        """
        with self.__lock:
            for client in self.__clients:
                if client.get_name() == name:
                    return client
        return None

    def __add_client(self, name: str, runtime_id: int) -> bool:
        """
        Adds a client to the system

        :param name: Name of the client to add
        :param runtime_id: Current runtime id of the client
        :return: Whether adding the client was successful
        """
        if self.get_client(name) is None:
            with self.__lock:
                buf_client = SmarthomeClient(name, runtime_id)
                self.__clients.append(buf_client)
                return True
        return False

    def get_all_clients(self) -> [SmarthomeClient]:
        """Returns a list of all saved clients"""
        with self.__lock:
            return self.__clients
        pass

    @staticmethod
    def __trigger_client(client: SmarthomeClient):
        """
        Reports an activity signal from a client

        :param client: Client to report the activity of
        """
        print("Triggering Activity on Client: '{}'".format(client.get_name()))
        client.trigger_activity()

    def __get_or_create_client(self, name: str, runtime_id: int) -> Optional[SmarthomeClient]:
        """
        Searches for a client with the name, creates it if necessary and returns the client

        :param name: Client to add or get
        :param runtime_id: Current runtime id of the client
        :return: The client object if possible, None if something went wrong
        """
        local_client = self.get_client(name)
        if local_client is None:
            success = self.__add_client(name, runtime_id)
            local_client = self.get_client(name)
            if local_client is None or not success:
                return None
        return local_client

    def __get_or_create_client_from_request(self, req: Request) -> Optional[SmarthomeClient]:
        """Searches for a client with the name, creates it if necessary and returns the client"""
        if "runtime_id" not in req.get_payload():
            print("Received heartbeat is missing 'runtime_id'")
            return None

        if not isinstance(req.get_payload()["runtime_id"], int):
            print("Received heartbeat has non-integer 'runtime_id'")
            return None

        local_client = self.__get_or_create_client(req.get_sender(), req.get_payload()["runtime_id"])
        if local_client is None:
            print("Something went completely wrong while creating client")
            return None

        self.__trigger_client(local_client)
        local_client.update_runtime_id(req.get_payload()["runtime_id"])

        return local_client

    def __ask_for_update(self, client: SmarthomeClient):
        """Sends out a request asking the selected client to send an update"""
        out_req = Request("smarthome/sync",
                          gen_req_id(),
                          "<bridge>",
                          client.get_name(),
                          {"server_time": int(time.time() / 1000)})
        self.__network_gadget.send_request(out_req, timeout=0)

    def restart_client(self, client: SmarthomeClient) -> bool:
        """Sends out a request to restart the client and"""

        return client_control_methods.reboot_client(client.get_name(),
                                                    "<bridge>",
                                                    self.__network_gadget)

    # endregion

    # region CHARACTERISTIC METHODS

    def update_characteristic_on_gadget(self, gadget_name: str, characteristic: CharacteristicIdentifier,
                                        value: int) -> (CharacteristicUpdateStatus, Gadget):
        """Updates a single characteristic of the selected gadget"""
        with self.__lock:
            for buf_gadget in self.__gadgets:
                if buf_gadget.get_name() == gadget_name:
                    return buf_gadget.update_characteristic(characteristic, value), buf_gadget
        return CharacteristicUpdateStatus.general_error, None

    def update_characteristic_from_client(self, gadget_name: str, characteristic: CharacteristicIdentifier,
                                          value: int) -> CharacteristicUpdateStatus:
        """Updates a single characteristic of the selected gadget"""
        update_status, gadget = self.update_characteristic_on_gadget(gadget_name, characteristic, value)
        if update_status == CharacteristicUpdateStatus.update_successful:
            self.update_characteristic_on_connectors(gadget, characteristic, value)
        return update_status

    def update_characteristic_on_clients(self, gadget: Gadget, characteristic: CharacteristicIdentifier,
                                         value: int) -> bool:
        """Forwards a characteristic update to the clients"""

        req_id = gen_req_id()

        buf_request = Request("smarthome/remotes/gadget/to_client/update",
                              req_id,
                              "<bridge>",
                              gadget.get_host_client(),
                              {
                                  "name": gadget.get_name(),
                                  "characteristic": int(characteristic),
                                  "value": value
                              })

        # Sends the request and does not wait for any answer
        self.__network_gadget.send_request(buf_request, 0)
        return False

    def update_characteristic_from_connector(self, gadget_name: str, characteristic: CharacteristicIdentifier,
                                             value: int, sender) -> CharacteristicUpdateStatus:
        """Gets an characteristic update from a connector and forwards it to every other connector and the clients"""
        update_status, gadget = self.update_characteristic_on_gadget(gadget_name, characteristic, value)
        if update_status == CharacteristicUpdateStatus.update_successful:
            # Update characteristic on clients
            self.update_characteristic_on_clients(gadget, characteristic, value)

            # Update characteristic on every other sender
            self.update_characteristic_on_connectors(gadget, characteristic, value, sender)

        return update_status

    def update_characteristic_on_connectors(self, gadget: Gadget, characteristic: CharacteristicIdentifier,
                                            value: int, exclude=None) -> bool:
        for connector in self.__connectors:
            if exclude is not None and connector != exclude:
                connector.update_characteristic(gadget.get_name(), characteristic, value)
        return True

    # endregion

    # region GADGET METHODS

    def get_gadget(self, gadget_name: str) -> Optional[Gadget]:
        """Returns the data for the selected gadget"""
        with self.__lock:
            for buf_gadget in self.__gadgets:
                if buf_gadget.get_name() == gadget_name:
                    return buf_gadget
            return None

    def get_all_gadgets(self):
        """Returns the data for all gadgets"""
        with self.__lock:
            return self.__gadgets

    def add_gadget(self, gadget: Gadget) -> bool:
        """Adds a gadget to the bridge"""
        if self.get_gadget(gadget.get_name()):
            print("Gadget with this name is already present")
            return False
        with self.__lock:
            print("Adding new gadget '{}'".format(gadget.get_name()))
            self.__gadgets.append(gadget)
            return True

    def delete_gadget(self, gadget: Gadget):
        """Deletes the passed gadget from all connectors and the local storage"""
        with self.__lock:
            for connector in self.__connectors:
                connector.remove_gadget(gadget)

            self.__gadgets.remove(gadget)

    # endregion

    # region CONNECTOR METHODS

    def get_all_connectors(self):
        """Returns the data for all connectors"""
        with self.__lock:
            return self.__connectors

    def __add_connector(self, c_type: HomeConnectorType, data: dict):
        if c_type == HomeConnectorType.homekit:
            try:
                buf_connector = HomeKitConnector(self,
                                                 own_name=data["name"],
                                                 mqtt_ip=data["ip"],
                                                 mqtt_port=data["port"])
                self.__connectors.append(buf_connector)
                print("Added 'HomeKit' connector '{}'".format(buf_connector.get_name()))
            except KeyError:
                print("Received broken connector config")

            return

    # endregion

    # region API

    def set_api_port(self, port: int):
        """Sets the port for the REST API"""
        with self.__lock:
            self.__api_port = port

    def get_api_port(self):
        """returns the current API port of the bridge"""
        with self.__lock:
            return self.__api_port

    def run_api(self):
        """Launches the REST API"""
        with self.__lock:
            self.__api_thread = BridgeAPIThread(parent=self)
            self.__api_thread.start()

    def set_socket_api_port(self, port: int):
        """Sets the port for the REST API"""
        with self.__lock:
            self.__ws_api_port = port

    def get_socket_api_port(self):
        """returns the current API port of the bridge"""
        with self.__lock:
            return self.__ws_api_port

    def run_socket_api(self):
        """Launches the REST API"""
        with self.__lock:
            self.__api_thread = BridgeSocketAPIThread(parent=self)
            self.__api_thread.start()

    # endregion

    def add_streaming_message_dict(self, message: dict):
        with self.__lock:
            self.__streaming_message_queue.append(json.dumps(message))

    def add_streaming_message(self, sender: str, status_code: str, message: str):
        self.add_streaming_message_dict({"sender": sender, "status": status_code, "message": message})

    def get_streaming_message(self) -> Optional[str]:
        with self.__lock:
            if self.__streaming_message_queue:
                return self.__streaming_message_queue.pop(0)
            return None


if __name__ == '__main__':
    # Argument-parser
    parser = argparse.ArgumentParser(description='Script to upload configs to the controller')
    parser.add_argument('--bridge_name', help='Network Name for the Bridge', type=str)
    parser.add_argument('--mqtt_ip', help='IP of the MQTT Broker', type=str)
    parser.add_argument('--mqtt_port', help='Port of the MQTT Broker', type=int)
    parser.add_argument('--mqtt_user', help='Username for the MQTT Broker', type=str)
    parser.add_argument('--mqtt_pw', help='mPassword for the MQTT Broker', type=str)
    parser.add_argument('--dummy_data', help='Adds dummy data for debugging.', action="store_true")
    parser.add_argument('--api_port', help='Port for the REST-API', type=int)
    parser.add_argument('--socket_port', help='Port for the Socket Server', type=int)
    ARGS = parser.parse_args()

    print("Launching Bridge")

    buf_bridge_name: str = get_sender()
    if ARGS.bridge_name:
        buf_bridge_name = ARGS.bridge_name

    if ARGS.mqtt_port:
        buf_mqtt_port: int = ARGS.mqtt_port
    else:
        print("No Port selected.")
        sys.exit(21)

    if ARGS.mqtt_ip:
        buf_mqtt_ip: str = ARGS.mqtt_ip
    else:
        print("No IP selected.")
        sys.exit(22)

    # Create Bridge
    bridge = MainBridge(buf_bridge_name, buf_mqtt_ip, buf_mqtt_port, None, None)

    # Insert dummy data if wanted
    if ARGS.dummy_data:
        print("Adding dummy data:")
        bridge.add_dummy_data()

    if ARGS.api_port:
        bridge.set_api_port(ARGS.api_port)
        bridge.run_api()
    else:
        print("No port for REST API configured.")

    if ARGS.socket_port:
        bridge.set_socket_api_port(ARGS.socket_port)
        bridge.run_socket_api()
    else:
        print("No port for Socket API configured.")
