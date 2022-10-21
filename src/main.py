#!/usr/bin/env python3
"""
main - The script builds and hosts the API using a command line interface.
"""

from importlib import import_module
from click import argument, echo, group, option
from dbml_builder import verify
from fastapi import FastAPI
from uvicorn import run as uvicorn_run
from pkgutil import iter_modules
from typing import List
from db import ENGINE
from generated import orm
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

DBML_PATH = '../askem.dbml'
DBML_VERSION = 'v0.11.4'
GENERATED_PATH = './generated'


def find_valid_routers() -> List[str]:
    """
    Generate list of module names that are possible to import
    """
    router = import_module('routers')
    return [module.name for module in iter_modules(router.__path__)]


def attach_router(api : FastAPI, router_name : str) -> None:
    """
    Import router module dynamically and attach it to the API

    At runtime, the routes to be used can be specified instead of
    being hardcoded.
    """
    router_package = import_module(f'routers.{router_name}')
    api.include_router(router_package.router, tags=[router_name])


def build_api(*args : str) -> FastAPI:
    """
    Build an API using a group of specified router modules
    """
    app = FastAPI(docs_url='/')
    for router_name in args if len(args) != 0 else find_valid_routers():
        attach_router(app, router_name)
    return app


def init_dev_db_content():
    """
    Initialize tables in the connected DB
    """
    orm.Base.metadata.create_all(ENGINE)
    with Session(ENGINE) as session:
        need_framework = session.query(orm.Framework).first() == None
        need_person = session.query(orm.Person).first() == None
        if need_framework: 
            framework = orm.Framework(
                id = 0,
                version = "dummy",
                name = "dummy",
                semantics = {},
            )
            session.add(framework)
        if need_person:
            person = orm.Person(
                id = 0,
                name = "Jane Doe",
                email = "sample",
                org = "sample",
                website = "sample",
                is_registered = True
            )
            session.add(person)
        session.commit()


@group()
def main() -> None:
    """
    Manage the data store API service
    """
    pass


@main.command()
@option('--host', default='0.0.0.0', type=str, help='Address for the API')
@option('--port', default=8000, type=int, help='Port to expose API')
@option('--dev', default=True, type=bool, help='Set development flag')
@argument('endpoint', nargs=-1)
def start(host: str, port: int, dev: bool, endpoint: str) -> None:
    """
    Execute data store API using uvicorn
    """
    try:
        assert verify(DBML_VERSION, GENERATED_PATH)
    except AssertionError:
        echo('Failed to start: version mismatch. DBML has either been updated or generated schemas have been modified by users')
        exit()
    if dev:
        try:
            init_dev_db_content()
        except OperationalError:
            echo('WARNING: DB NOT CONNECTED')
    api = build_api(*endpoint)
    uvicorn_run(
      api,
      host=host,
      port=port,
    )


if __name__ == "__main__":
    main()
