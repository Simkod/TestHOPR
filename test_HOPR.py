import asyncio
import pytest
import requests
import websockets

from string import Template
from prometheus_client.parser import text_string_to_metric_families

#Global Variables
myApiAuthToken = '%th1s-IS-a-S3CR3T-ap1-PUSHING-b1ts-TO-you%'
APIurlbase = Template('http://localhost:$APIport/api/v2/') 

APIPorts = {'node1': 13301,
            'node2': 13302,
            'node3': 13303,
            'node4': 13304,
            'node5': 13305}

relevantMetricKeys = ['core_counter_forwarded_messages_total',
                      'core_counter_received_messages_total',
                      'core_counter_sent_messages_total',
                      ]

def HTTPgetRequest(url, headers):
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response

def HTTPpostRequest(url, headers, data):
    response = requests.post(url, json=data, headers=headers)
    response.raise_for_status()
    return response

#utilties
def getNodeMetrics(node):
    url = APIurlbase.substitute(APIport=APIPorts[node]) + 'node/metrics'
    headers = {'accept': 'application/json',
               'x-auth-token': myApiAuthToken}
    response = HTTPgetRequest(url, headers)

    metrics = response.content.decode('UTF-8')
    metrics = text_string_to_metric_families(metrics)
    return metrics

def getRelevantMetricsFor(node):
    nodeMetrics = getNodeMetrics(node)
    nodeMetricsDict = {}
    for family in nodeMetrics:
        for sample in family.samples:
            if sample.name in relevantMetricKeys:
                nodeMetricsDict[sample.name] = sample.value
    return nodeMetricsDict

def getNodeAddressFor(node):
    url = APIurlbase.substitute(APIport=APIPorts[node]) + 'account/addresses'
    headers = {'accept': 'application/json',
               'x-auth-token': myApiAuthToken}
    
    response = HTTPgetRequest(url, headers)
    responseJson = response.json()
    return responseJson['hopr']

def test_channelsForAllNodes():
    for node, APIPort in APIPorts.items():
        includingClosed='false'
        url = APIurlbase.substitute(APIport=APIPort) + 'channels/?includingClosed=' + includingClosed
        headers = {'accept': 'application/json',
                   'x-auth-token': myApiAuthToken}

        response = HTTPgetRequest(url, headers)
        responseJson = response.json()

        assert len(responseJson['incoming']) == (len(APIPorts)-1), node + ' does not have an incoming channel from every node'
        assert len(responseJson['outgoing']) == (len(APIPorts)-1), node + ' does not have an outgoing channel to every node'

def test_pingNodes():
    for pingerNode, pingerAPIPort in APIPorts.items():
        for pingNode, pingAPIPort in APIPorts.items():
            if pingerNode == pingNode:
                continue
            data = {'peerId': getNodeAddressFor(pingNode)}
            url = APIurlbase.substitute(APIport=pingerAPIPort) + 'node/ping'
            headers = {'accept': 'application/json',
                    'x-auth-token': myApiAuthToken,
                    'Content-Type': 'application/json'}
            response = HTTPpostRequest(url, headers, data)
            assert response.status_code == 200, 'Ping from ' + pingerNode + ' to ' + pingNode + ' was unsuccessful.'

async def sendMessage(senderNode, receiverNode, message, path, hops):
    await asyncio.sleep(0.1) #Let time for WebsocketClient to connect
    recipientAddress = getNodeAddressFor(receiverNode)

    url = APIurlbase.substitute(APIport=APIPorts[senderNode]) + 'messages'
    headers = {'accept': 'application/json',
               'x-auth-token': myApiAuthToken,
               'Content-Type': 'application/json'}
    data = {'body': message,
            'recipient': recipientAddress,
            'path' : path,
            'hops': hops}
    response = HTTPpostRequest(url, headers, data)

    assert response.status_code == 202, "Message was not sent successfully"

async def connectWebsocket(receiverNode):
    print('ConnectWebsocket Started')
    websocketAPIbaseurl = Template('ws://localhost:$APIport/api/v2/messages/websocket?apiToken=$AuthToken')
    url = websocketAPIbaseurl.substitute(APIport=APIPorts[receiverNode], AuthToken=myApiAuthToken)
    async with websockets.connect(url) as websocket:
        message = await websocket.recv()
        assert message, 'No message received at ' + receiverNode

@pytest.mark.asyncio
async def case_singlemessage(senderNode, receiverNode, message, hops, path=[]):

    senderMetricsBefore = getRelevantMetricsFor(senderNode)
    receiverMetricsBefore = getRelevantMetricsFor(receiverNode)

    # Relaycheck
    if path:
        pathNodes = path
        path = [ getNodeAddressFor(path[0]), getNodeAddressFor(path[1]) ]
        relay1MetricsBefore = getRelevantMetricsFor(pathNodes[0])
        relay2MetricsBefore = getRelevantMetricsFor(pathNodes[1])

    #Websocket Client and Message
    await asyncio.gather(
        connectWebsocket(receiverNode),
        sendMessage(senderNode, receiverNode, message, path, hops))
    
    senderMetricsAfter = getRelevantMetricsFor(senderNode)
    receiverMetricsAfter = getRelevantMetricsFor(receiverNode)
    assert senderMetricsBefore['core_counter_sent_messages_total'] == senderMetricsAfter['core_counter_sent_messages_total']-1 , 'Message was not sent'
    assert receiverMetricsBefore['core_counter_received_messages_total'] == receiverMetricsAfter['core_counter_received_messages_total']-1 , 'Message was not received'

    # Relaycheck
    if path:
        relay1MetricsAfter = getRelevantMetricsFor(pathNodes[0])
        relay2MetricsAfter = getRelevantMetricsFor(pathNodes[1])
        assert relay1MetricsBefore['core_counter_forwarded_messages_total'] == relay1MetricsAfter['core_counter_forwarded_messages_total']-1 , 'Message was not relayed through ' + path[0]
        assert relay2MetricsBefore['core_counter_forwarded_messages_total'] == relay2MetricsAfter['core_counter_forwarded_messages_total']-1 , 'Message was not relayed through ' + path[1]

#not in use, just for limitation demonstration
@pytest.mark.asyncio
async def case_messageInTraffic(senderNode, receiverNode, message, hops, trafficNodes, path=[] ):

    senderMetricsBefore = getRelevantMetricsFor(senderNode)
    receiverMetricsBefore = getRelevantMetricsFor(receiverNode)

    #With multiple asynchronous messages non of the messages were delivered - Limitation(see documentation for details)
    await asyncio.gather(
        connectWebsocket(receiverNode),
        sendMessage(senderNode, receiverNode, message, path, hops),
        sendMessage(trafficNodes[0], trafficNodes[1], 'covertraffic1', [], 3),
        sendMessage(trafficNodes[0], trafficNodes[1], 'covertraffic1', [], 3),
        sendMessage(trafficNodes[0], trafficNodes[1], 'covertraffic1', [], 3),
        sendMessage(trafficNodes[0], trafficNodes[1], 'covertraffic1', [], 3),
        sendMessage(trafficNodes[0], trafficNodes[1], 'covertraffic1', [], 3),
        sendMessage(trafficNodes[0], trafficNodes[1], 'covertraffic1', [], 3)
        )
    await asyncio.sleep(0.2)
    
    senderMetricsAfter = getRelevantMetricsFor(senderNode)
    receiverMetricsAfter = getRelevantMetricsFor(receiverNode)

    assert senderMetricsBefore['core_counter_sent_messages_total'] == senderMetricsAfter['core_counter_sent_messages_total']-2 , 'Not all messages were not sent'
    assert receiverMetricsBefore['core_counter_received_messages_total'] == receiverMetricsAfter['core_counter_received_messages_total']-2 , 'Not all messages were received'


def test_node1to5_1hop_notraffic():
    senderNode = 'node1'
    receiverNode = 'node5'
    message = "This is the message."
    hops = 1

    asyncio.run(case_singlemessage(senderNode, receiverNode, message, hops))

def test_node2to4_setpath_notraffic_relaycheck():
    senderNode = 'node2'
    receiverNode = 'node4'
    message = "This is a test message." 
    path = [ 'node1', 'node5']
    hops = 2 #ignored if path is set

    asyncio.run(case_singlemessage(senderNode, receiverNode, message, hops, path))

def test_node3to1_3hops_nopath_notraffic():
    senderNode = 'node3'
    receiverNode = 'node1'
    message = "This is the message."
    hops = 3 

    asyncio.run(case_singlemessage(senderNode, receiverNode, message, hops))

#With multiple asynchronous messages non of the messages were delivered - Limitation(see documentation for details)
""" def test_node1to5_3hops_nopath_heavytraffic():
    senderNode = 'node1'
    receiverNode = 'node5'
    trafficNodes = ['node1', 'node2', 'node3']
    message = "This is the message."
    hops = 3 

    asyncio.run(case_messageInTraffic(senderNode, receiverNode, message, hops, trafficNodes)) """