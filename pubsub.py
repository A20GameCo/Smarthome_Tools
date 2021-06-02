"""Module for the publisher/subscriber pattern metaclasses"""
from abc import abstractmethod, ABCMeta
from request import Request


class Subscriber(metaclass=ABCMeta):

    @abstractmethod
    def receive(self, req: Request):
        pass


class Publisher(metaclass=ABCMeta):

    __subscriber_clients: list

    def __init__(self):
        self.__subscriber_clients = []

    def subscribe(self, client: Subscriber):
        if client not in self.__subscriber_clients:
            self.__subscriber_clients.append(client)

    def unsubscribe(self, client: Subscriber):
        self.__subscriber_clients.remove(client)

    def _publish(self, req: Request):
        for subscriber in self.__subscriber_clients:
            subscriber.receive(req)
