import json
import os
from gadgetlib import CharacteristicIdentifier, CharacteristicUpdateStatus

from flask import Flask, redirect, url_for, request, jsonify, Response
from flask_cors import cross_origin, CORS
from jsonschema import validate, ValidationError

# https://pythonbasics.org/flask-http-methods/

__new_request_received = 1
__schema_data = {}



def load_schemas() -> dict:
    schema_data = {}
    for f_name in os.listdir('json_schemas'):
        if f_name.endswith('.json'):
            with open(os.path.join("json_schemas", f_name), 'r') as file:
                buf_schema_data = json.load(file)
                schema_data[f_name] = buf_schema_data
    return schema_data


def generate_valid_response(json_body: dict, json_schema_name: str, status_code: int = 200) -> Response:
    global __schema_data

    try:
        json_schema = __schema_data[json_schema_name]
        validate(json_body, json_schema)
        response = jsonify(json_body)

        response.status_code = status_code

        # response.headers.add('Access-Control-Allow-Origin', '*')
        # response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        # response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response

    except KeyError:
        print(f"Json Schema '{json_schema_name}' was not found")
        response = {"status": f"Internal Server Error while validating response: "
                              f"Validation failed. Please file a bug report."}

    except ValidationError:
        print(f"Validating response with '{json_schema_name}' failed.")
        response = {"status": f"Internal Server Error while validating response: Validation schema not found. "
                              f"Please file a bug report."}

    return generate_valid_response(response, 'default_message.json', status_code=500)


def run_api(bridge, port: int):
    """Methods that launches the rest api to read, write and update gadgets via HTTP"""
    global __schema_data

    __schema_data = load_schemas()
    print(f"Loaded {len(__schema_data)} schemas.")

    app = Flask(__name__)

    app.config['CORS_HEADERS'] = 'Content-Type'

    cors = CORS(app)

    @app.route('/')
    @cross_origin()
    def root():
        """
        Flask API response method
        Category: System
        Title: Root
        Description: Sends back some example paths to get actual information from
        Input Schema: None
        Output Schema: 'default_message.json'
        :return: Response to the request
        """
        bridge.add_streaming_message("API", __new_request_received, "/")
        res_data = {"status": "Use /info, /gadgets, /connectors or /clients to get bridge info and consult the api "
                              "documentation on 'https://github.com/johannesgrothe/Smarthome_Bridge/wiki/api'"}

        return generate_valid_response(res_data, "default_message.json")

    @app.route('/gadgets', methods=['GET'])
    @cross_origin()
    def get_all_gadgets():
        """
        Flask API response method
        Category: Gadgets
        Title: Read Gadget Information
        Description: Reads information for all the gadgets from the bridge
        Input Schema: 'api_get_all_gadgets_response.json'
        Output Schema: None
        :return: Response to the request
        """
        bridge.add_streaming_message("API", __new_request_received, "/gadgets")
        gadget_list = bridge.get_all_gadgets()

        out_gadget_list: [dict] = []
        for gadget in gadget_list:
            json_gadget = gadget.serialized()
            out_gadget_list.append(json_gadget)

        buf_res = {"gadgets": out_gadget_list,
                   "gadget_count": len(out_gadget_list)}

        return generate_valid_response(buf_res, 'api_get_all_gadgets_response.json')

    @app.route('/clients', methods=['GET'])
    @cross_origin()
    def get_all_clients():
        """
        Flask API response method
        Category: Clients
        Title: Read Client Information
        Description: Reads information for all the clients from the bridge
        Input Schema: None
        Output Schema: 'api_get_all_clients_response.json'
        :return: Response to the request
        """
        bridge.add_streaming_message("API", __new_request_received, "/clients")
        client_list = bridge.get_all_clients()

        out_client_list: [dict] = []
        for client in client_list:
            json_client = client.serialized()
            out_client_list.append(json_client)

        buf_res = {"clients": out_client_list,
                   "client_count": len(out_client_list)}

        return generate_valid_response(buf_res, 'api_get_all_clients_response.json')

    @app.route('/info', methods=['GET'])
    @cross_origin()
    def get_info():
        """
        Flask API response method
        Category: System
        Title: Read Bridge Information
        Description: Reads information about the bridge
        Input Schema: None
        Output Schema: 'api_get_info_response.json'
        :return: Response to the request
        """
        bridge.add_streaming_message("API", __new_request_received, "/info")
        bridge_name = bridge.get_bridge_name()
        gadget_list = bridge.get_all_gadgets()
        connector_list = bridge.get_all_connectors()
        client_list = bridge.get_all_clients()

        buf_res = {"bridge_name": bridge_name,
                   "software_commit": bridge.get_sw_commit(),
                   "software_branch": bridge.get_sw_branch(),
                   "running_since": bridge.get_time_launched().strftime("%Y-%m-%d %H:%M:%S"),
                   "gadget_count": len(gadget_list),
                   "connector_count": len(connector_list),
                   "client_count": len(client_list),
                   "platformio_version": bridge.get_host_pio_version(),
                   "python_version": bridge.get_host_python_version(),
                   "pipenv_version": bridge.get_host_pipenv_version(),
                   "git_version": bridge.get_host_git_version()}

        return generate_valid_response(buf_res, 'api_get_info_response.json')

    @app.route('/connectors', methods=['GET'])
    @cross_origin()
    def get_all_connectors():
        """
        Flask API response method
        Category: Connectors
        Title: Read Connector Information
        Description: Reads information for all the connectors configured on the bridge
        Input Schema: None
        Output Schema: 'api_get_connectors_response.json'
        :return: Response to the request
        """
        bridge.add_streaming_message("API", __new_request_received, "/connectors")
        connector_list = bridge.get_all_connectors()

        out_gadget_list: [dict] = []
        for connector in connector_list:
            json_connector = connector.serialized()
            out_gadget_list.append(json_connector)

        buf_res = {"connectors": out_gadget_list,
                   "connector_count": len(out_gadget_list)}

        return generate_valid_response(buf_res, 'api_get_connectors_response.json')

    @app.route('/clients/<client_name>/restart', methods=['POST'])
    @cross_origin()
    def restart_client(client_name):
        """
        Category: Clients
        Title: Restart Client
        Description: Restarts the client specified in the url parameter
        Input Schema: None
        Output Schema: 'default_message.json'
        Param <client_name>: Name of the client that should be rebooted.
        :return: Response to the request
        """
        bridge.add_streaming_message("API", __new_request_received, f"/clients/{client_name}/restart")
        gadget = bridge.get_client(client_name)
        if gadget is None:
            return generate_valid_response({"status": "Gadget name was not found"},
                                           "default_message.json",
                                           status_code=404)
        success = bridge.restart_client(gadget)
        if success:
            return generate_valid_response({"status": "Reboot was successful"}, "default_message.json")
        return generate_valid_response({"status": "Error triggering reboot on client"},
                                       "default_message.json",
                                       status_code=400)

    @app.route('/system/get_serial_ports', methods=['GET'])
    @cross_origin()
    def get_serial_ports():
        """
        Category: System
        Title: Read Serial Ports
        Description: Reads all of the serial ports available to the bridge
        Input Schema: None
        Output Schema: 'api_get_serial_ports_response.json'
        :return: Response to the request
        """
        bridge.add_streaming_message("API", __new_request_received, f"/system/serial_ports")
        serial_ports = bridge.get_serial_ports()
        return generate_valid_response({"serial_port_count": len(serial_ports), "serial_ports": serial_ports},
                                       'api_get_serial_ports_response.json')

    @app.route('/system/flash_software', methods=['POST'])
    @cross_origin()
    def flash_software():
        """
        Category: Clients
        Title: Flash Software
        Description: Flashes the newest software commit of the selected branch to the chip connected to the selected serial port
        Input Schema: None
        Output Schema: 'default_message.json'
        Param 'branch_name': Software-branch shat should be flashed to the chip
        Param 'serial_port': Serial port the chip is connected to
        :return: Response to the request
        """
        bridge.add_streaming_message("API", __new_request_received, "/system/flash_software")
        branch_name = request.args.get('branch_name')
        serial_port = request.args.get('serial_port')

        success, status = bridge.flash_software(branch_name, serial_port)

        str_branch = branch_name if branch_name is not None else "master"
        str_port = serial_port if serial_port is not None else "default"

        suc_resp = f"Flashing software from '{str_branch}' on port '{str_port}'started."
        suc_resp += f"Connect to port {bridge.get_socket_api_port()} to view progress."

        if not success:
            return generate_valid_response({"status": f"Error flashing software from '{str_branch}' on "
                                                      f"port '{str_port}': {status}"},
                                           'default_message.json',
                                           status_code=400)

        return generate_valid_response({"status": suc_resp}, 'default_message.json')

    @app.route('/system/configs', methods=['GET'])
    @cross_origin()
    def get_config_names():
        """
        Category: System
        Title: Read Bridge Configs
        Description: Reads the names of the stored client configs from the bridge
        Input Schema: None
        Output Schema: 'api_get_config_names_response.json'
        :return: Response to the request
        """
        config_names = bridge.load_config_names()
        return generate_valid_response({"config_names": config_names}, 'api_get_config_names_response.json')

    @app.route('/system/configs/<config_name>', methods=['GET'])
    @cross_origin()
    def get_config(config_name: str):
        """
        Category: System
        Title: Read Config
        Description: Reads the config with the selected name from the bridge
        Input Schema: None
        Output Schema: 'api_get_config_data_response.json'
        Param <config_name>: Name of the config to read
        :return: Response to the request
        """
        config_data = bridge.load_config(config_name)
        return generate_valid_response({"config_data": config_data}, 'api_get_config_data_response.json')

    @app.route('/clients/<client_name>/write_config', methods=['POST'])
    @cross_origin()
    def write_config_to_network(client_name: str):
        """
        Category: Clients
        Title: Write Config to Network Client
        Description: Writes the config contained in the request body to the selected client
        Input Schema: 'client_config.json'
        Output Schema: 'default_message.json'
        Param <client_name>: Name of the client to write the config to
        :return: Response to the request
        """
        json_payload = request.json
        config = json_payload

        if config:
            try:
                validate(config, __schema_data['client_config.json'])
                success, status = bridge.write_config_to_network_chip(config, client_name)
            except ValidationError:
                success = False
                status = "Config schema validation failed."
            except KeyError:
                return generate_valid_response({"status": "Encountered error while trying to validate: missing scheme"},
                                               'client_config.json',
                                               status_code=500)

            if not success:
                response = {"status": f"Error writing config to client '{client_name}': {status}"}
                return generate_valid_response(response,
                                               'default_message.json',
                                               status_code=400)
        else:
            response = {"status": f"No config selected."}
            return generate_valid_response(response,
                                           'default_message.json',
                                           status_code=400)

        response = {"status": f"Writing config to client '{client_name}' was successful."}
        return generate_valid_response(response,
                                       'default_message.json')

    @app.route('/system/write_config', methods=['POST'])
    @cross_origin()
    def write_config_to_serial():
        """
        Category: Clients
        Title: Write Config to Serial Client
        Description: Writes the config contained in the request body to the client connected via serial
        Input Schema: 'client_config.json'
        Output Schema: 'default_message.json'
        Param 'serial_port': Can be set to manually select the serial port the client is connected to
        :return: Response to the request
        """
        serial_port = request.args.get('serial_port')

        json_payload = request.json
        config = json_payload

        if config:
            try:
                validate(config, __schema_data['client_config.json'])
                success, status = bridge.write_config_to_chip(config, serial_port)
            except ValidationError:
                success = False
                status = "Config schema validation failed."
            except KeyError:
                return generate_valid_response({"status": "Encountered error while trying to validate: missing scheme"},
                                               'default_message.json',
                                               status_code=500)

            if not success:
                response = {"status": f"Error writing config on port '{serial_port}': {status}"}
                return generate_valid_response(response,
                                               'default_message.json',
                                               status_code=400)
        else:
            response = {"status": f"No config selected."}
            return generate_valid_response(response,
                                           'default_message.json',
                                           status_code=400)

        response: dict = {"status": f"Writing config on port '{serial_port}' was successful."}
        return generate_valid_response(response,
                                       'default_message.json')

    @app.route('/gadgets/<gadget_name>/set_characteristic', methods=['POST'])
    @cross_origin(origin="*")
    def set_gadget_characteristic(gadget_name: str):
        """
        Category: Gadgets
        Title: Set characteristic of Gadget
        Description: Sets the characteristic, contained in the request body, on the specified gadget
        Input Schema: 'api_set_gadget_characteristic.json'
        Output Schema: 'default_message.json'
        Param <gadget_name>: Name of the gadget the characteristic shall be changed on
        :return: Response to the request
        """
        json_payload = request.json

        print(request.method)
        if json_payload:
            try:
                validate(json_payload, __schema_data['api_set_gadget_characteristic.json'])
            except ValidationError:
                response = {"status": f"Error setting gadget_characteristic for '{gadget_name}'" + f"json_payload: '{json_payload}'"}
                return generate_valid_response(response,
                                               'default_message.json',
                                               status_code=400)

        buf_characteristic_id = CharacteristicIdentifier(json_payload["characteristic"])
        value = json_payload["value"]
        result = bridge.update_characteristic_from_connector(gadget_name, buf_characteristic_id, value, None)
        if result == CharacteristicUpdateStatus.update_successful or result == CharacteristicUpdateStatus.no_update_needed:
            return generate_valid_response({"status": "Update successful or not needed"},
                                           'default_message.json',
                                           status_code=200)
        if result == CharacteristicUpdateStatus.unknown_characteristic:
            return generate_valid_response({"status": "provided an unknown characteristic"},
                                           'default_message.json',
                                           status_code=400)
        if result == CharacteristicUpdateStatus.update_failed:
            return generate_valid_response({"status": "Update failed, cause unknown"},
                                           'default_message.json',
                                           status_code=400)
        if result == CharacteristicUpdateStatus.general_error:
            return generate_valid_response({"status": "congrats you bricked the system, now go back and try again"},
                                           'default_message.json',
                                           status_code=500)

    # @app.route('/gadgets/all/<yolo>/<xxx>', methods=['POST', 'GET'])
    # def login():
    #     if request.method == 'POST':
    #         user = request.form['nm']
    #         return redirect(url_for('success', name=user))
    #     else:
    #         user = request.args.get('nm')
    #         return redirect(url_for('success', name=user))

    app.run(host='0.0.0.0', port=port)
