import asyncio
import requests
import json
import time
import websockets
from string import Template
#from websockets.sync.client import connect
from prometheus_client.parser import text_string_to_metric_families

 #Global Variables
myApiAuthToken = '%th1s-IS-a-S3CR3T-ap1-PUSHING-b1ts-TO-you%'
APIurlbase = Template('http://localhost:$APIport/api/v2/') 
websocketAPIbaseurl = Template('ws://localhost:$APIport/api/v2/messages/websocket?apiToken=$AuthToken')

APIPorts = {'node1': 13301,
            'node2': 13302,
            'node3': 13303,
            'node4': 13304,
            'node5': 13305}

relevantMetricKeys = ['connect_counter_client_relayed_packets_total',
                    'connect_counter_direct_packets_total',
                    'connect_counter_server_relayed_packets_total',
                    'core_counter_forwarded_messages_total',
                    'core_counter_packets_total',
                    'core_counter_received_messages_total',
                    'core_counter_received_successful_acks_total',
                    'core_counter_sent_acks_total',
                    'core_counter_sent_messages_total',
                    'core_ethereum_counter_indexer_announcements_total',
                    'core_ethereum_counter_num_send_transactions_total',
                    'core_gauge_num_incoming_channels',
                    'core_gauge_num_outgoing_channels',
                    'core_histogram_path_length_bucket']

nodeHOPRAddresses = {}

#Functions for communication
def HTTPgetRequest(url, headers):
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response

def HTTPpostRequest(url, headers, data):
    response = requests.post(url, json=data, headers=headers)
    response.raise_for_status()
    return response

def connectWebSocket(node):
    nodeAPIPort = APIPorts['node5']
    while True:
        with websockets.connect(websocketAPIbaseurl.substitute(APIport=nodeAPIPort, AuthToken=myApiAuthToken)) as websocket:
            message = websocket.recv()
        #print(f"Received: {message}")

#Prints
def printResponseJson(jsonObject):
    print(json.dumps(jsonObject, indent=2))

def printDict(dict):
    for key, value in dict.items():
        print(key, ':', value)
    print('\n')

#utilties
def getNodeMetrics(nodeAPIPort):
    url = APIurlbase.substitute(APIport=nodeAPIPort) + 'node/metrics'
    headers = {'accept': 'application/json',
               'x-auth-token': myApiAuthToken}
    response = requests.get(url, headers=headers) #because response is plain text
    response.raise_for_status()

    metrics = response.content.decode('UTF-8')
    metrics = text_string_to_metric_families(metrics)
    return metrics

def getRelevantMetricsFor(node):
    nodeMetrics = getNodeMetrics(APIPorts[node])
    nodeMetricsDict = {}
    for family in nodeMetrics:
        for sample in family.samples:
            if sample.name in relevantMetricKeys:
                nodeMetricsDict[sample.name] = sample.value
    return nodeMetricsDict

def getNodeAddresses():
    for node, APIPort in APIPorts.items():
        url = APIurlbase.substitute(APIport=APIPort) + 'account/addresses'
        headers = {'accept': 'application/json',
                   'x-auth-token': myApiAuthToken}
    
        response = HTTPgetRequest(url, headers)
        responseJson = response.json()
        nodeHOPRAddresses[node] = responseJson['hopr']
    return nodeHOPRAddresses

def sendMessage(senderNode, receiverNode, message, path, hops):
    recipientAddress = nodeHOPRAddresses[receiverNode]

    url = APIurlbase.substitute(APIport=APIPorts[senderNode]) + 'messages'
    headers = {'accept': 'application/json',
               'x-auth-token': myApiAuthToken,
               'Content-Type': 'application/json'}
    data = {'body': message,
            'recipient': recipientAddress,
            'path' : path,
            'hops': hops}
    response = HTTPpostRequest(url, headers, data)
    time.sleep(0.25)
    return response

#Setup Tests
def testChannelsForAllNodes():
    for node, APIPort in APIPorts.items():
        includingClosed='false'
        url = APIurlbase.substitute(APIport=APIPort) + 'channels/?includingClosed=' + includingClosed
        headers = {'accept': 'application/json',
                   'x-auth-token': myApiAuthToken}

        response = HTTPgetRequest(url, headers)
        responseJson = response.json()

        assert len(responseJson['incoming']) == (len(APIPorts)-1), node + 'is does not have an "incoming" channel from every node'
        assert len(responseJson['outgoing']) == (len(APIPorts)-1), node + 'is does not have an "outgoing" channel to every node'
    print('Incoming and outgoing channels - OK\n')

def pingNodes():
    for node, APIPort in APIPorts.items():
        for HOPRaddress in nodeHOPRAddresses.values():
            if HOPRaddress == nodeHOPRAddresses[node]:
                continue
            data = {'peerId': HOPRaddress}
            url = APIurlbase.substitute(APIport=APIPort) + 'node/ping'
            headers = {'accept': 'application/json',
                    'x-auth-token': myApiAuthToken,
                    'Content-Type': 'application/json'}
            response = HTTPpostRequest(url, headers, data)
    print('All node pinged from all nodes - OK')

#TestCases
def test_sendMessage(senderNode, receiverNode, message, path, hops):
    senderMetricsBefore = getRelevantMetricsFor(senderNode)
    receiverMetricsBefore = getRelevantMetricsFor(receiverNode)

    #asyncio.get_event_loop().run_until_complete(connectWebSocket(receiverNode))
    connectWebSocket(receiverNode)

    #sign message

    sendMessage(senderNode, receiverNode, message, path, hops)

    senderMetricsAfter = getRelevantMetricsFor(senderNode)
    receiverMetricsAfter = getRelevantMetricsFor(receiverNode)

    assert receiverMetricsBefore['core_counter_received_messages_total'] == receiverMetricsAfter['core_counter_received_messages_total']-1 , 'Message was not received'

    #Received Checker 2 - WebSocket

    #Send Check
        #With Metrics
        #With response

    # Check tickets received for relaying - ???


def main():

    #wait = input('Start the docker cluster by with     docker run --rm -d -p 8545:8545 -p 13301-13305:13301-13305 -p 18081-18085:18081-18085 -p 19091-19095:19091-19095 -p 19501-19505:19501-19505 --name pluto_cluster gcr.io/hoprassociation/hopr-pluto:1.92.7  and Press Enter to start the tests./n')

    nodeHOPRAddresses = getNodeAddresses()
    print('Node HOPR addresses:')
    printDict(nodeHOPRAddresses)

    pingNodes()

    testChannelsForAllNodes()

    senderNode = 'node1'
    receiverNode = 'node5'
    message = "This is the message."
    path = []
    hops = 1
    test_sendMessage(senderNode, receiverNode, message, path, hops)

if __name__ == "__main__":
    main()
