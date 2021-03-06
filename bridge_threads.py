from threading import Thread
from chip_flasher import flash_chip
from bridge import MainBridge

from network_connector import NetworkConnector
from typing import Optional
from mqtt_connector import MQTTConnector
from request import Request
import api
import socket_api
import client_control_methods


class BridgeMQTTThread(Thread):
    __parent_object: MainBridge
    __mqtt_connector: MQTTConnector

    def __init__(self, parent: MainBridge, connector: MQTTConnector):
        super().__init__()
        print("Creating Bridge MQTT Thread")
        self.__parent_object = parent
        self.__mqtt_connector = connector

    def run(self):
        print("Starting Bridge MQTT Thread")
        while True:
            buf_req: Optional[Request] = self.__mqtt_connector.get_request()
            if buf_req:
                self.__parent_object.handle_request(buf_req)


class BridgeAPIThread(Thread):
    __parent_object: MainBridge

    def __init__(self, parent: MainBridge):
        super().__init__()
        print("Creating Bridge API Thread")
        self.__parent_object = parent

    def run(self):
        print("Starting Bridge API Thread")
        buf_api_port = self.__parent_object.get_api_port()

        if buf_api_port == 0:
            print("API port not configured")
            return

        print("Launching API")
        api.run_api(self.__parent_object, buf_api_port)


class ChipConfigFlasherThread(Thread):
    __streaming_callback = None
    __config: dict
    __client_name: str
    __sender: str
    __network: NetworkConnector

    def __init__(self, sender: str, network: NetworkConnector, config: dict, client_name: str, callback=None):
        super().__init__()
        print("Chip Software Flasher Thread")
        self.__config = config
        self.__streaming_callback = callback
        self.__sender = sender
        self.__network = network
        self.__client_name = client_name

    def run(self):
        print("Starting config flasher thread")
        client_control_methods.write_config(self.__client_name,
                                            self.__config,
                                            self.__sender,
                                            self.__network,
                                            self.__streaming_callback)
        print("Flashing done.")


class ChipSWFlasherThread(Thread):
    __streaming_callback = None
    __branch: str
    __force_reset: bool
    __upload_port: Optional[str]

    def __init__(self, branch: str, force_reset: bool, serial_port: Optional[str] = None, callback=None):
        super().__init__()
        print("Chip Software Flasher Thread")
        self.__branch = branch
        self.__force_reset = force_reset
        self.__upload_port = serial_port
        self.__streaming_callback = callback

    def run(self):
        print("Starting chip flasher Thread")
        flash_chip(self.__branch,
                   self.__force_reset,
                   self.__upload_port,
                   self.__streaming_callback)
        print("Flashing done.")


class BridgeSocketAPIThread(Thread):
    __parent_object: MainBridge

    def __init__(self, parent: MainBridge):
        super().__init__()
        print("Creating Bridge Websocket API Thread")
        self.__parent_object = parent

    def run(self):
        print("Starting Bridge Websocket API Thread")
        buf_api_port = self.__parent_object.get_socket_api_port()

        if buf_api_port == 0:
            print("Websocket API port not configured")
            return

        socket_api.run_socket_api(self.__parent_object, buf_api_port)