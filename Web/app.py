#! /usr/bin/env python
# -*- coding: utf-8 -*-
"""This is the main Python script to run Cisco Command Center

This script runs the Flask web server which handles the API backend (/api)
and the Vue.js frontend (/) for Cisco Command Center.
"""


import json
import os
import pprint
import time
import uuid
from bson.json_util import dumps
from bson.objectid import ObjectId
from datetime import datetime, timedelta

import flask
import pymongo
import requests
import xmltodict

from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, render_template, request
from flask_compress import Compress
from flask_cors import CORS
from modules import amp_client
from modules import pxgrid_controller
from requests.auth import HTTPBasicAuth

# Load the .env
load_dotenv()

# Configuration
if os.getenv('PRODUCTION') == "True":
    ENV = 'production'
else:
    ENV = 'development'
    DEBUG = True
    TESTING = True

COMPRESS_MIMETYPES = ['text/html', 'text/css', 'text/xml', 'application/json', 'application/javascript']
COMPRESS_LEVEL = 6
COMPRESS_MIN_SIZE = 500

# Instantiate the app
app = Flask(__name__, static_folder="./frontend/dist/static", template_folder="./frontend/dist")
app.config.from_object(__name__)

# Enable Flask-Compress
Compress(app)

# Enable CORS
CORS(app)


# Sanity check route
@app.route('/ping', methods=['GET'])
def ping_pong():
    return jsonify('pong!')


# Events Functions
@app.route('/api/event/<event_id>', methods=['GET'])
def get_event(event_id):
    """A function to retrieve an event from the database and return it as JSON"""

    # Connect to the MongoDB instance
    db_client = pymongo.MongoClient("mongodb://{}/".format(os.getenv("MONGO_INITDB_ADDRESS")),
                                    username=os.getenv("MONGO_INITDB_ROOT_USERNAME"),
                                    password=os.getenv("MONGO_INITDB_ROOT_PASSWORD"))

    # Use the 'commandcenter' database
    command_center_db = db_client['commandcenter']

    # Use the 'events' collection from the 'commandcenter' database
    command_center_events = command_center_db['events']

    # Set up a basic query filter
    query_filter = {}

    # Filter for the specified event ID
    query_filter['_id'] = ObjectId(event_id)

    # Get the event
    event = command_center_events.find_one(query_filter)

    # Make a human readable timestamp
    event['formatted_timestamp'] = event["timestamp"].strftime("%b %d, %Y %H:%M:%S UTC")

    # Parse the bson event into json
    event = json.loads(dumps(event))

    # Set up a response object
    response_object = {
        'status': 'success',
        'event': [event],
    }

    return jsonify(response_object)


@app.route('/api/events', methods=['GET'])
def get_events():
    """A function to retrieve events from the database and return them as JSON"""

    # Connect to the MongoDB instance
    db_client = pymongo.MongoClient("mongodb://{}/".format(os.getenv("MONGO_INITDB_ADDRESS")),
                                    username=os.getenv("MONGO_INITDB_ROOT_USERNAME"),
                                    password=os.getenv("MONGO_INITDB_ROOT_PASSWORD"))

    # Use the 'commandcenter' database
    command_center_db = db_client['commandcenter']

    # Use the 'events' collection from the 'commandcenter' database
    command_center_events = command_center_db['events']

    # Set up a basic query filter
    query_filter = {}

    # If the host IP is specified, then only return those events.
    if 'host_ip' in request.args:
        query_filter['src_ip'] = request.args['host_ip']

    # If a timeframe is specified, then use it.
    if 'timeframe' in request.args:
        timeframe = int(request.args['timeframe'])
        query_date = datetime.utcnow().replace(microsecond=0) - timedelta(hours=timeframe)
        query_filter['timestamp'] = {'$gte': query_date}

    # If a product is specified, then use it.
    if 'product' in request.args:
        query_filter['product'] = {'$eq': request.args['product']}

    # If an event name is specified, then use it.
    if 'event_name' in request.args:
        query_filter['event_name'] = {'$eq': request.args['event_name']}

    # Projection to return a subset of fields
    projection = {
        'event_name': 1,
        'event_details': 1,
        'product': 1,
        'src_ip': 1,
        'timestamp': 1
    }

    # Get the events
    latest_events = command_center_events.find(query_filter, projection).sort('timestamp', -1)

    # Set up a response object
    response_object = {
        'status': 'success',
        'events': [],
    }

    # Iterate through all events
    for event in latest_events:

        # Make a human readable date if one doesn't exist - starting to do this on event import now
        if 'formatted_timestamp' not in event.keys():
            event['formatted_timestamp'] = event["timestamp"].strftime("%b %d, %Y %H:%M:%S UTC")

        # Append the event to the response
        response_object['events'].append(json.loads(dumps(event)))

    return jsonify(response_object)


@app.route('/api/events-over-time', methods=['GET'])
def get_events_over_time():
    """A function to retrieve event counts from the database aggregated into intervals and return them as JSON"""

    # Connect to the MongoDB instance
    db_client = pymongo.MongoClient("mongodb://{}/".format(os.getenv("MONGO_INITDB_ADDRESS")),
                                    username=os.getenv("MONGO_INITDB_ROOT_USERNAME"),
                                    password=os.getenv("MONGO_INITDB_ROOT_PASSWORD"))

    # Use the 'commandcenter' database
    command_center_db = db_client['commandcenter']

    # Use the 'events' collection from the 'commandcenter' database
    command_center_events = command_center_db['events']

    # Set up a basic query filter
    query_filter = {}

    # If the host IP is specified, then only return those events.
    if 'host_ip' in request.args:
        query_filter['src_ip'] = request.args['host_ip']

    # If a timeframe is specified, then use it.
    if 'timeframe' in request.args:
        timeframe = int(request.args['timeframe'])
        query_date = datetime.utcnow().replace(microsecond=0) - timedelta(hours=timeframe)
        query_filter['timestamp'] = {'$gte': query_date}

    # If a product is specified, then use it.
    if 'product' in request.args:
        query_filter['product'] = {'$eq': request.args['product']}

    # If an event name is specified, then use it.
    if 'event_name' in request.args:
        query_filter['event_name'] = {'$eq': request.args['event_name']}

    # Get the aggregated events
    aggregated_events = command_center_events.aggregate([
        {"$match": query_filter},
        {"$group":
            {"_id":
                {"$toDate":
                    {"$subtract": [
                        {"$toLong": "$timestamp"},
                        {"$mod": [
                            {"$toLong": "$timestamp"},
                            1000 * 60 * 5
                        ]}
                    ]}},
                "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
    ])

    # Set up a response object
    response_object = {
        'status': 'success',
        'event_counts': [],
    }

    # Iterate through all events
    for event in aggregated_events:

        # Append the event to the response
        response_object['event_counts'].append(json.loads(dumps(event)))

    return jsonify(response_object)


# AMP Functions
@app.route('/api/amp/computer/<ip_address>', methods=['GET'])
def get_amp_computer(ip_address):
    """A function to retrieve AMP computer data and return it as JSON"""

    # Return HTTP 204 if not configured
    if not os.getenv("AMP_API_CLIENT_ID") or not os.getenv("AMP_API_KEY"):
        return json_no_content()

    # Create an AMP API Client
    client = amp_client.AmpClient(client_id=os.getenv("AMP_API_CLIENT_ID"),
                                  api_key=os.getenv("AMP_API_KEY"))

    # Get the computers that have been at the internal IP
    response = client.get_computers(internal_ip=ip_address)

    if response:
        # Return a JSON formatted response
        return jsonify(response)
    else:
        return json_no_content()


@app.route('/api/amp/computer/<connector_guid>/group', methods=['POST'])
def set_amp_computer_group(connector_guid):
    """A function to set the Group for a specific AMP computer"""

    # Return HTTP 204 if not configured
    if not os.getenv("AMP_API_CLIENT_ID") or not os.getenv("AMP_API_KEY"):
        return json_no_content()

    # Create an AMP API Client
    client = amp_client.AmpClient(client_id=os.getenv("AMP_API_CLIENT_ID"),
                                  api_key=os.getenv("AMP_API_KEY"))

    # Patch the computer to change the group
    response = client.patch_computer(connector_guid=connector_guid, data=request.get_json())

    if response:
        # Return a JSON formatted response
        return jsonify(response)
    else:
        return json_no_content()


@app.route('/api/amp/groups', methods=['GET'])
def get_amp_groups():
    """A function to get all groups from AMP"""

    # Return HTTP 204 if not configured
    if not os.getenv("AMP_API_CLIENT_ID") or not os.getenv("AMP_API_KEY"):
        return json_no_content()

    # Create an AMP API Client
    client = amp_client.AmpClient(client_id=os.getenv("AMP_API_CLIENT_ID"),
                                  api_key=os.getenv("AMP_API_KEY"))

    # Get the groups that exist in AMP
    response = client.get_groups()

    if response:
        # Return a JSON formatted response
        return jsonify(response)
    else:
        return json_no_content()


@app.route('/api/amp/computer/<connector_guid>/isolation', methods=['GET'])
def get_amp_computer_isolation(connector_guid):
    """A function to get the AMP isolation status of a computer"""

    # Create an AMP API Client
    client = amp_client.AmpClient(client_id=os.getenv("AMP_API_CLIENT_ID"),
                                  api_key=os.getenv("AMP_API_KEY"))

    # Get the AMP Isolation status
    response = client.get_isolation(guid=connector_guid)

    if response:
        # Return a JSON formatted response
        return jsonify(response)
    else:
        return json_no_content()


@app.route('/api/amp/computer/<connector_guid>/isolation', methods=['DELETE'])
def delete_amp_computer_isolation(connector_guid):
    """A function to delete the AMP isolation status of a computer"""

    # Create an AMP API Client
    client = amp_client.AmpClient(client_id=os.getenv("AMP_API_CLIENT_ID"),
                                  api_key=os.getenv("AMP_API_KEY"))

    # Delete the AMP Isolation status
    response = client.delete_isolation(guid=connector_guid, data=request.get_json())

    if response:
        # Return a JSON formatted response
        return jsonify(response)
    else:
        return json_no_content()


@app.route('/api/amp/computer/<connector_guid>/isolation', methods=['PUT'])
def put_amp_computer_isolation(connector_guid):
    """A function to put the AMP isolation status of a computer"""

    # Create an AMP API Client
    client = amp_client.AmpClient(client_id=os.getenv("AMP_API_CLIENT_ID"),
                                  api_key=os.getenv("AMP_API_KEY"))

    # Put the AMP Isolation status
    response = client.put_isolation(guid=connector_guid, data=request.get_json())

    if response:
        # Return a JSON formatted response
        return jsonify(response)
    else:
        return json_no_content()


# Stealthwatch Functions
@app.route('/api/stealthwatch/host-snapshot', methods=['GET'])
def get_stealthwatch_host_snapshot():
    """A function to get host snapshots from Stealthwatch"""

    # Return HTTP 204 if not configured
    if (
        not os.getenv("STEALTHWATCH_API_ADDRESS") or
        not os.getenv("STEALTHWATCH_API_USERNAME") or
        not os.getenv("STEALTHWATCH_API_PASSWORD")
    ):
        return json_no_content()

    # Build the API URL
    api_url = "https://{}/smc/swsService/hosts".format(os.getenv("STEALTHWATCH_API_ADDRESS"))

    # Get the XML that we'll send to Stealthwatch
    xml = _get_stealthwatch_host_snapshot_xml(request.args['host_ip'])

    # Send the request to Stealthwatch
    http_request = requests.post(api_url,
                                 auth=HTTPBasicAuth(os.getenv("STEALTHWATCH_API_USERNAME"),
                                                    os.getenv("STEALTHWATCH_API_PASSWORD")),
                                 data=xml,
                                 verify=False)

    # Check to make sure the POST was successful
    if http_request.status_code == 200:

        # Return JSON formatted flows
        return jsonify(xmltodict.parse(http_request.text)['soapenc:Envelope']['soapenc:Body'])

    else:
        print('Stealthwatch Connection Failure - HTTP Return Code: {}\nResponse: {}'.format(http_request.status_code, http_request.text))
        exit()


def _get_stealthwatch_host_snapshot_xml(host_ip):
    """A function to generate XML to fetch host snapshots from Stealthwatch"""

    # Build the XML
    return_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
    <soapenv:Envelope xmlns:soapenv=\"http://schemas.xmlsoap.org/soap/envelope/\">
        <soapenv:Body>
            <getHostSnapshot>
                <host-filter domain-id=\"{}\">
                    <host-selection>
                        <ip-address-selection value=\"{}\"/>
                    </host-selection>
                </host-filter>
            </getHostSnapshot>
        </soapenv:Body>
    </soapenv:Envelope>""".format(os.getenv("STEALTHWATCH_API_TENANT"), host_ip)

    return return_xml


@app.route('/api/stealthwatch/flows', methods=['GET'])
def get_stealthwatch_flows():
    """A function to get recent flows from Stealthwatch"""

    # Return HTTP 204 if not configured
    if (
        not os.getenv("STEALTHWATCH_API_ADDRESS") or
        not os.getenv("STEALTHWATCH_API_USERNAME") or
        not os.getenv("STEALTHWATCH_API_PASSWORD")
    ):
        return json_no_content()

    # Build the API URL
    api_url = "https://{}/smc/swsService/flows".format(os.getenv("STEALTHWATCH_API_ADDRESS"))

    # Change the number of hours to milliseconds for Stealthwatch
    duration = int(request.args['timeframe']) * 60 * 60 * 1000

    # Get the XML that we'll send to Stealthwatch
    xml = _get_stealthwatch_flows_xml(duration, request.args['host_ip'])

    # Send the request to Stealthwatch
    http_request = requests.post(api_url,
                                 auth=HTTPBasicAuth(os.getenv("STEALTHWATCH_API_USERNAME"),
                                                    os.getenv("STEALTHWATCH_API_PASSWORD")),
                                 data=xml,
                                 verify=False)

    # Check to make sure the POST was successful
    if http_request.status_code == 200:

        response = xmltodict.parse(http_request.text)['soapenc:Envelope']['soapenc:Body']

        if response['getFlowsResponse']['flow-list']:
            # Return JSON formatted flows
            return jsonify(response)
        else:
            return json_no_content()

    else:
        print('Stealthwatch Connection Failure - HTTP Return Code: {}\nResponse: {}'.format(http_request.status_code, http_request.text))
        exit()


def _get_stealthwatch_flows_xml(duration, host_ip):
    """A function to generate XML to fetch flows from Stealthwatch"""

    # Build the XML
    return_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
    <soapenc:Envelope xmlns:soapenc=\"http://schemas.xmlsoap.org/soap/envelope/\">
        <soapenc:Body>
            <getFlows>
                <flow-filter max-rows=\"10000\" domain-id=\"{}\" remove-duplicates=\"true\" order-by=\"TOTAL_BYTES\" order-by-desc=\"true\" include-interface-data=\"false\">
                    <date-selection>
                        <time-window-selection duration=\"{}\"/>
                    </date-selection>
                    <host-selection>
                        <host-pair-selection direction=\"BETWEEN_SELECTION_1_SELECTION_2\">
                            <selection-1>
                                <ip-address-list-selection>
                                    <ip-address value=\"{}\" />
                                </ip-address-list-selection>
                            </selection-1>
                        </host-pair-selection>
                    </host-selection>
                    <protocols>1,6,17</protocols>
                </flow-filter>
            </getFlows>
        </soapenc:Body>
    </soapenc:Envelope>""".format(os.getenv("STEALTHWATCH_API_TENANT"), duration, host_ip)

    return return_xml


# ISE Functions
@app.route('/api/ise_actions', methods=['GET'])
def get_ise_actions():
    """A function to get the ANC profiles from ISE"""

    # Return HTTP 204 if not configured
    if (
        not os.getenv("ISE_API_ADDRESS") or
        not os.getenv("ISE_API_USERNAME") or
        not os.getenv("ISE_API_PASSWORD")
    ):
        return json_no_content()

    api_url = "https://{}:{}@{}:9060/ers/config/ancpolicy".format(os.getenv("ISE_API_USERNAME"),
                                                                  os.getenv("ISE_API_PASSWORD"),
                                                                  os.getenv("ISE_API_ADDRESS"))

    print("Fetching {}".format(api_url))

    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    # Get ISE ANC Policies
    http_request = requests.get(api_url, headers=headers, verify=False)

    # Check to make sure the GET was successful
    if http_request.status_code == 200:
        return jsonify(http_request.json())
    else:
        print('ISE Connection Failure - HTTP Return Code: {}\nResponse: {}'.format(http_request.status_code, http_request.text))
        exit()


@app.route('/api/ise_anc_status/<mac_address>', methods=['GET'])
def get_ise_anc_assignment(mac_address):
    """A function to look up the ISE ANC assignment for a given MAC address"""

    # Return HTTP 204 if not configured
    if (
        not os.getenv("ISE_API_ADDRESS") or
        not os.getenv("ISE_PXGRID_CLIENT_NAME")
    ):
        return json_no_content()

    pxgrid = pxgrid_controller.PxgridControl(os.getenv("ISE_API_ADDRESS"),
                                             os.getenv("ISE_PXGRID_CLIENT_NAME"),
                                             os.getenv("ISE_PXGRID_CERT_PATH"),
                                             os.getenv("ISE_PXGRID_KEY_PATH"))

    # Check to see if the account is enabled
    if pxgrid.account_activate()['accountState'] != 'ENABLED':
        print("pxGrid Account is not enabled.")
        return '', 403

    # Lookup the session service
    service_lookup_response = pxgrid.service_lookup('com.cisco.ise.config.anc')

    # Store the session service
    session_service = service_lookup_response['services'][0]

    # Build the URL to get session details
    url = session_service['properties']['restBaseUrl'] + '/getEndpointByMacAddress'

    # Run the session query
    pxgrid_response = pxgrid.send_rest_request(url, {"macAddress": mac_address})

    if pxgrid_response is not None:
        return jsonify(pxgrid_response)
    else:
        return json_no_content()


@app.route('/api/ise_anc_status', methods=['POST'])
def set_ise_anc_assignment():
    """A function to set the ISE ANC assignment for a given MAC address"""

    # Return HTTP 204 if not configured
    if (
        not os.getenv("ISE_API_ADDRESS") or
        not os.getenv("ISE_PXGRID_CLIENT_NAME")
    ):
        return json_no_content()

    pxgrid = pxgrid_controller.PxgridControl(os.getenv("ISE_API_ADDRESS"),
                                             os.getenv("ISE_PXGRID_CLIENT_NAME"),
                                             os.getenv("ISE_PXGRID_CERT_PATH"),
                                             os.getenv("ISE_PXGRID_KEY_PATH"))

    # Check to see if the account is enabled
    if pxgrid.account_activate()['accountState'] != 'ENABLED':
        print("pxGrid Account is not enabled.")
        return '', 403

    # Lookup the session service
    service_lookup_response = pxgrid.service_lookup('com.cisco.ise.config.anc')

    # Store the session service
    session_service = service_lookup_response['services'][0]

    # Build the URL to get session details
    url = session_service['properties']['restBaseUrl'] + '/applyEndpointByMacAddress'

    # Get the POST data from the request
    post_data = request.get_json()

    pxgrid_data = {
        "macAddress": post_data.get("mac_address"),
        "policyName": post_data.get("anc_policy")
    }

    # Run the session query
    pxgrid_response = pxgrid.send_rest_request(url, pxgrid_data)

    if pxgrid_response is not None:
        return jsonify(pxgrid_response)
    else:
        return json_no_content()


@app.route('/api/ise_anc_status/<mac_address>', methods=['DELETE'])
def clear_ise_anc_assignment(mac_address):
    """A function to clear the ISE ANC assignment for a given MAC address"""

    # Return HTTP 204 if not configured
    if (
        not os.getenv("ISE_API_ADDRESS") or
        not os.getenv("ISE_PXGRID_CLIENT_NAME")
    ):
        return json_no_content()

    pxgrid = pxgrid_controller.PxgridControl(os.getenv("ISE_API_ADDRESS"),
                                             os.getenv("ISE_PXGRID_CLIENT_NAME"),
                                             os.getenv("ISE_PXGRID_CERT_PATH"),
                                             os.getenv("ISE_PXGRID_KEY_PATH"))

    # Check to see if the account is enabled
    if pxgrid.account_activate()['accountState'] != 'ENABLED':
        print("pxGrid Account is not enabled.")
        return '', 403

    # Lookup the session service
    service_lookup_response = pxgrid.service_lookup('com.cisco.ise.config.anc')

    # Store the session service
    session_service = service_lookup_response['services'][0]

    # Build the URL to get session details
    url = session_service['properties']['restBaseUrl'] + '/clearEndpointByMacAddress'

    # Run the session query
    pxgrid_response = pxgrid.send_rest_request(url, {"macAddress": mac_address})

    if pxgrid_response is not None:
        return jsonify(pxgrid_response)
    else:
        return json_no_content()


@app.route('/api/ise_session_data/<ip_address>', methods=['GET'])
def get_ise_session_data(ip_address):
    """A function to look up the ISE session data for a given IP"""

    # Return HTTP 204 if not configured
    if (
        not os.getenv("ISE_API_ADDRESS") or
        not os.getenv("ISE_PXGRID_CLIENT_NAME")
    ):
        return json_no_content()

    pxgrid = pxgrid_controller.PxgridControl(os.getenv("ISE_API_ADDRESS"),
                                             os.getenv("ISE_PXGRID_CLIENT_NAME"),
                                             os.getenv("ISE_PXGRID_CERT_PATH"),
                                             os.getenv("ISE_PXGRID_KEY_PATH"))

    # Check to see if the account is enabled
    if pxgrid.account_activate()['accountState'] != 'ENABLED':
        print("pxGrid Account is not enabled.")
        return '', 403

    # Lookup the session service
    service_lookup_response = pxgrid.service_lookup('com.cisco.ise.session')

    # Store the session service
    session_service = service_lookup_response['services'][0]

    # Build the URL to get session details
    url = session_service['properties']['restBaseUrl'] + '/getSessionByIpAddress'

    # Run the session query
    pxgrid_response = pxgrid.send_rest_request(url, {"ipAddress": ip_address})

    if pxgrid_response is not None:
        return jsonify(pxgrid_response)
    else:
        return json_no_content()


# Helpers
def json_no_content():
    """A function to return an HTTP 204 with empty JSON"""

    response = make_response('', 204)
    response.mimetype = flask.current_app.config['JSONIFY_MIMETYPE']

    return response


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    return render_template("index.html")

if __name__ == '__main__':

    # Run the webserver
    app.run(host='0.0.0.0')
