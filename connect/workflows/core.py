"""
core.py

Provides the base LinuxForHealth workflow definition.
"""
import json
import logging
import connect.clients.nats as nats
import uuid
import xworkflows
from datetime import datetime
from fastapi import Response
from httpx import AsyncClient
from connect.clients.kafka import (get_kafka_producer,
                                   KafkaCallback)
from connect.config import nats_sync_subject
from connect.exceptions import LFHError
from connect.routes.data import LinuxForHealthDataRecordResponse
from connect.support.encoding import (encode_from_dict,
                                      encode_from_str,
                                      decode_to_str,
                                      ConnectEncoder)


logger = logging.getLogger(__name__)


class CoreWorkflowDef(xworkflows.Workflow):
    """
    Implements the base LinuxForHealth workflow definition.
    """
    states = (
        ('parse', "Parse"),
        ('validate', "Validate"),
        ('transform', "Transform"),
        ('persist', "Persist"),
        ('transmit', "Transmit"),
        ('sync', "Synchronize"),
        ('error', "Error")
    )

    transitions = (
        ('do_validate', 'parse', 'validate'),
        ('do_transform', 'validate', 'transform'),
        ('do_persist', ('parse', 'validate', 'transform'), 'persist'),
        ('do_transmit', 'persist', 'transmit'),
        ('do_sync', ('persist', 'transmit'), 'sync'),
        ('handle_error', ('parse', 'validate', 'transform', 'persist', 'transmit', 'sync'), 'error')
    )

    initial_state = 'parse'


class CoreWorkflow(xworkflows.WorkflowEnabled):
    """
    Implements the base LinuxForHealth workflow.
    """
    def __init__(self, **kwargs):
        self.message = kwargs['message']
        self.data_format = kwargs.get('data_format', None)
        self.origin_url = kwargs['origin_url']
        self.start_time = None
        self.use_response = False
        self.verify_certs = kwargs['certificate_verify']
        self.lfh_exception_topic = 'LFH_EXCEPTION'
        self.lfh_id = kwargs['lfh_id']
        self.transmit_server = kwargs.get('transmit_server', None)
        self.do_sync = kwargs.get('do_sync', True)

    state = CoreWorkflowDef()

    @xworkflows.transition('do_validate')
    def validate(self):
        """
        Override to provide data validation.
        """
        pass

    @xworkflows.transition('do_transform')
    def transform(self):
        """
        Override to transform from one form or protocol to another (e.g. HL7v2 to FHIR
        or FHIR R3 to R4).
        """
        pass

    @xworkflows.transition('do_persist')
    async def persist(self):
        """
        Store the message in Kafka for persistence after converting it to the LinuxForHealth
        message format.

        Input:
        self.message: The object to be stored in Kafka
        self.origin_url: The originating endpoint url
        self.data_format: The data_format of the data being stored
        self.start_time: The transaction start time

        Output:
        self.message: The python dict for LinuxForHealthDataRecordResponse instance with
            the original object instance in the data field as a byte string
        """

        logger.debug(f'{self.__class__.__name__}: incoming message = {self.message}')
        logger.debug(f'{self.__class__.__name__}: incoming message type = {type(self.message)}')

        if hasattr(self.message, 'dict'):
            encoded_data = encode_from_dict(self.message.dict())
        elif isinstance(self.message, dict):
            encoded_data = encode_from_dict(self.message)
        else:
            encoded_data = encode_from_str(self.message)

        message = {
            'uuid': str(uuid.uuid4()),
            'lfh_id': self.lfh_id,
            'creation_date': str(datetime.utcnow().replace(microsecond=0)) + 'Z',
            'store_date': str(datetime.utcnow().replace(microsecond=0)) + 'Z',
            'consuming_endpoint_url': self.origin_url,
            'data_format': self.data_format,
            'data': encoded_data,
            'target_endpoint_url': self.transmit_server

        }
        response = LinuxForHealthDataRecordResponse(**message)

        kafka_producer = get_kafka_producer()
        kafka_cb = KafkaCallback()
        storage_start = datetime.now()
        await kafka_producer.produce_with_callback(self.data_format, response.json(),
                                                   on_delivery=kafka_cb.get_kafka_result)

        storage_delta = datetime.now() - storage_start
        logger.debug(f' {self.__class__.__name__} persist: stored resource location = {kafka_cb.kafka_result}')
        total_time = datetime.utcnow() - self.start_time
        message['elapsed_storage_time'] = storage_delta.total_seconds()
        message['elapsed_total_time'] = total_time.total_seconds()
        message['data_record_location'] = kafka_cb.kafka_result
        message['status'] = kafka_cb.kafka_status

        response = LinuxForHealthDataRecordResponse(**message).dict()
        logger.debug(f'{self.__class__.__name__} persist: outgoing message = {response}')
        self.message = response

    @xworkflows.transition('do_transmit')
    async def transmit(self, response: Response):
        """
        Transmit the message to an external service via HTTP,
        if self.transmit_server is defined by the workflow.

        Input:
        self.message: The python dict for a LinuxForHealthDataRecordResponse instance
            containing the data to be transmitted
        response: The FastAPI Response object
        self.verify_certs: Whether to verify certs, True/False, set at the application level in config.py
        self.transmit_server: The url of external server to transmit the data to

        Output:
        The updated Response object
        """
        if self.transmit_server and response:
            resource_str = decode_to_str(self.message['data'])
            resource = json.loads(resource_str)

            transmit_start = datetime.now()
            self.message['transmit_date'] = str(transmit_start.replace(microsecond=0)) + 'Z'
            try:
                async with AsyncClient(verify=self.verify_certs) as client:
                    result = await client.post(self.transmit_server, json=resource)
            except:
                transmit_delta = datetime.now() - transmit_start
                self.message['elapsed_transmit_time'] = transmit_delta.total_seconds()
                raise
            transmit_delta = datetime.now() - transmit_start
            self.message['elapsed_transmit_time'] = transmit_delta.total_seconds()

            response.body = result.text
            response.status_code = result.status_code

            # Merge result headers into response headers with overwrite
            for key, value in result.headers.items():
                if key not in ['Content-Length', 'Content-Language', 'Date']:
                    response.headers[key] = value

            # Set original LFH message uuid in response header
            response.headers['LinuxForHealth-MessageId'] = str(self.message['uuid'])

            self.use_response = True

    @xworkflows.transition('do_sync')
    async def synchronize(self):
        """
        Send the message to NATS subscribers for synchronization across LFH instances.
        """
        if self.do_sync:
            nats_client = await nats.get_nats_client()
            msg_str = json.dumps(self.message, cls=ConnectEncoder)
            await nats_client.publish(nats_sync_subject, bytearray(msg_str, 'utf-8'))

    @xworkflows.transition('handle_error')
    async def error(self, error) -> str:
        """
        On error, store the error message and the current message in
        Kafka for persistence and further error handling.

        Input:
        self.message: The python dict for the current message being processed

        :param error: The error message tp be stored in kafka
        :return: The json string for the error message stored in Kafka
        """
        logger.debug(f'{self.__class__.__name__} error: incoming error = {error}')
        data_str = json.dumps(self.message, cls=ConnectEncoder)
        data = json.loads(data_str)

        message = {
            'uuid': uuid.uuid4(),
            'error_date': datetime.utcnow().replace(microsecond=0),
            'error_msg': str(error),
            'data': data
        }
        error = LFHError(**message)

        kafka_producer = get_kafka_producer()
        kafka_cb = KafkaCallback()
        await kafka_producer.produce_with_callback(self.lfh_exception_topic, error.json(),
                                                   on_delivery=kafka_cb.get_kafka_result)

        logger.debug(f'{self.__class__.__name__} error: stored resource location = {kafka_cb.kafka_result}')
        message['data_record_location'] = kafka_cb.kafka_result
        error = LFHError(**message).json()
        logger.debug(f'{self.__class__.__name__} error: outgoing message = {error}')
        return error

    async def run(self, response: Response):
        """
        Run the workflow according to the defined states.  Override to extend or exclude states
        for a particular implementation.

        :return: the response instance, with updated body and status_code
        """
        self.start_time = datetime.utcnow()

        try:
            logger.info(f'Running {self.__class__.__name__}, message={self.message}')
            self.validate()
            self.transform()
            await self.persist()
            await self.transmit(response)
            await self.synchronize()
            return self.message
        except Exception as ex:
            msg = await self.error(ex)
            raise Exception(msg)
