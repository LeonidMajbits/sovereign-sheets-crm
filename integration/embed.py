"""Host integration surface. No process, thread, scheduler or credential is started.

The existing lab runtime provisions private roots/configuration, constructs one
Database+Engine+Broker and routes its authenticated requests to Broker.handle.
For authenticated Unix socket transport, host UnixBrokerServer in its lifecycle.
Call publisher.run(service_actor) from the EXISTING paced lifecycle, not per agent.
"""
from crm.db import Database
from crm.engine import Engine
from crm.service import Broker, UnixBrokerServer

def build_local_broker(runtime_root, *, cursor_key, artifact_registry=None, publisher_factory=None):
    db=Database(runtime_root)
    engine=Engine(db,artifact_registry=artifact_registry)
    publisher=publisher_factory(engine) if publisher_factory else None
    broker=Broker(engine,publisher=publisher,cursor_key=cursor_key)
    return db,engine,broker
