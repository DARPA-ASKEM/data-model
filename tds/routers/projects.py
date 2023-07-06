"""
CRUD operations for projects
"""

import json
from logging import Logger
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Query as FastAPIQuery
from fastapi import Response, status
from sqlalchemy.engine.base import Engine
from sqlalchemy.orm import Query, Session

from tds.autogen import orm
from tds.db import entry_exists, es_client, list_by_id, request_rdb
from tds.lib.projects import adjust_project_assets, save_project_assets
from tds.modules.artifact.response import artifact_response
from tds.modules.dataset.response import dataset_response
from tds.modules.model.utils import model_list_fields, model_list_response
from tds.modules.model_configuration.response import configuration_response
from tds.modules.simulation.response import simulation_response
from tds.modules.workflow.response import workflow_response
from tds.operation import create, delete, retrieve, update
from tds.schema.project import Project, ProjectMetadata
from tds.schema.resource import ResourceType, get_resource_orm, get_schema_description
from tds.settings import settings

logger = Logger(__name__)
router = APIRouter()
es = es_client()

es_list_response = {
    ResourceType.models: {"function": model_list_response, "fields": model_list_fields},
    ResourceType.model_configurations: {
        "function": configuration_response,
        "fields": None,
    },
    ResourceType.datasets: {"function": dataset_response, "fields": None},
    ResourceType.simulations: {"fields": None, "function": simulation_response},
    ResourceType.workflows: {"fields": None, "function": workflow_response},
    ResourceType.artifacts: {"fields": None, "function": artifact_response},
}

es_resources = [
    ResourceType.datasets,
    ResourceType.models,
    ResourceType.model_configurations,
    ResourceType.simulations,
    ResourceType.workflows,
    ResourceType.artifacts,
]


@router.get("")
def list_projects(
    page_size: int = 50, page: int = 0, rdb: Engine = Depends(request_rdb)
) -> List[ProjectMetadata]:
    """
    Retrieve all projects
    """
    return list_by_id(rdb.connect(), orm.Project, page_size, page)


@router.get("/{id}", **retrieve.fastapi_endpoint_config)
def get_project(id: int, rdb: Engine = Depends(request_rdb)) -> Project:
    """
    Retrieve project
    """
    if entry_exists(rdb.connect(), orm.Project, id):
        with Session(rdb) as session:
            project = session.query(orm.Project).get(id)
            parameters: Query[orm.ProjectAsset] = session.query(
                orm.ProjectAsset
            ).filter(orm.ProjectAsset.project_id == id)
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return Project.from_orm(project, list(parameters))


@router.delete("/{id}", **retrieve.fastapi_endpoint_config)
def deactivate_project(id: int, rdb: Engine = Depends(request_rdb)) -> Project:
    """
    Deactivate project
    """
    if entry_exists(rdb.connect(), orm.Project, id):
        with Session(rdb) as session:
            project = session.query(orm.Project).get(id)

        # set to dict and active to false
        project_ = project.__dict__
        project_.pop("_sa_instance_state")
        project_["active"] = False

        with Session(rdb) as session:
            session.query(orm.Project).filter(orm.Project.id == id).update(project_)
            session.commit()

    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return Response(
        headers={
            "content-type": "application/json",
        },
        content=json.dumps({"id": id, "status": project_["active"]}),
    )


@router.post("", **create.fastapi_endpoint_config)
def create_project(payload: Project, rdb: Engine = Depends(request_rdb)) -> Response:
    """
    Create project and return its ID
    """
    with Session(rdb) as session:
        project_payload = payload.dict()
        # pylint: disable-next=unused-variable
        concept_payload = project_payload.pop("concept")  # TODO: Save ontology term
        assets = project_payload.pop("assets")
        for resource_type in assets:
            current_orm = get_resource_orm(resource_type)
            if not all(
                (
                    entry_exists(rdb.connect(), current_orm, id)
                    for id in assets[resource_type]
                )
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Not all listed assets exist.",
                )
        project = orm.Project(**project_payload)
        session.add(project)
        session.commit()
        id: int = project.id
        save_project_assets(id, assets, session)
        session.commit()
    logger.info("new project created: %i", id)
    return Response(
        status_code=status.HTTP_201_CREATED,
        headers={
            "location": f"/api/projects/{id}",
            "content-type": "application/json",
        },
        content=json.dumps({"id": id}),
    )


@router.put("/{id}", **update.fastapi_endpoint_config)
def update_project(
    id: int, payload: Project, rdb: Engine = Depends(request_rdb)
) -> Response:
    """
    Update project
    """
    if entry_exists(rdb.connect(), orm.Project, id):
        project_payload = payload.dict()
        project_payload.pop("concept")  # TODO: Save ontology term
        project_payload.pop("id")
        assets = project_payload.pop("assets")
        with Session(rdb) as session:
            session.query(orm.Project).filter(orm.Project.id == id).update(
                project_payload
            )
            adjust_project_assets(id, assets, session)
            session.commit()
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return Response(
        headers={
            "content-type": "application/json",
        },
        content=json.dumps({"id": id}),
    )


@router.delete(
    "/{project_id}/assets/{resource_type}/{resource_id}",
    **delete.fastapi_endpoint_config,
)
def delete_asset(
    project_id: int,
    resource_type: ResourceType,
    resource_id: int | str,
    rdb: Engine = Depends(request_rdb),
) -> Response:
    """
    Remove asset
    """
    with Session(rdb) as session:
        project_assets = list(
            session.query(orm.ProjectAsset).filter(
                orm.ProjectAsset.project_id == project_id,
                orm.ProjectAsset.resource_type == resource_type,
                orm.ProjectAsset.resource_id == str(resource_id),
            )
        )
        if len(project_assets) == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        session.delete(project_assets[0])
        session.commit()
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
        )


@router.post(
    "/{project_id}/assets/{resource_type}/{resource_id}",
    **create.fastapi_endpoint_config,
)
def create_asset(
    project_id: int,
    resource_type: ResourceType,
    resource_id: int | str,
    rdb: Engine = Depends(request_rdb),
) -> Response:
    """
    Create asset and return its ID
    """
    with Session(rdb) as session:
        identical_count = (
            session.query(orm.ProjectAsset)
            .filter(
                orm.ProjectAsset.project_id == project_id,
                orm.ProjectAsset.resource_id == str(resource_id),
                orm.ProjectAsset.resource_type == resource_type,
            )
            .count()
        )

        if identical_count == 0:
            project_asset = orm.ProjectAsset(
                project_id=project_id,
                resource_id=str(resource_id),
                resource_type=resource_type,
            )
            session.add(project_asset)
            session.commit()
            id: int = project_asset.id

            logger.info("new asset created: %i", id)
            return Response(
                status_code=status.HTTP_201_CREATED,
                headers={
                    "content-type": "application/json",
                },
                content=json.dumps({"id": id}),
            )
        return Response(status.HTTP_409_CONFLICT)


@router.get("/{id}/assets", **retrieve.fastapi_endpoint_config)
def get_project_assets(
    id: int,
    types: Optional[List[ResourceType]] = FastAPIQuery(
        default=[
            ResourceType.datasets,
            ResourceType.models,
            ResourceType.model_configurations,
            ResourceType.publications,
            ResourceType.simulations,
            ResourceType.workflows,
            ResourceType.artifacts,
        ]
    ),
    rdb: Engine = Depends(request_rdb),
):
    """
    Retrieve project assets
    """
    if entry_exists(rdb.connect(), orm.Project, id):
        with Session(rdb) as session:
            # project = session.query(orm.Project).get(id)
            assets: Query[orm.ProjectAsset] = session.query(orm.ProjectAsset).filter(
                orm.ProjectAsset.project_id == id
            )
            assets_key_ids = {type: [] for type in types}
            for asset in list(assets):
                if asset.resource_type in types:
                    assets_key_ids[asset.resource_type].append(asset.resource_id)

            assets_key_objects = {}
            for key in assets_key_ids:
                orm_type = get_resource_orm(key)
                orm_schema = get_schema_description(key)
                if key in es_resources:
                    responder = es_list_response[key]
                    index_singular = key if key[-1] != "s" else key.rstrip("s")
                    index = f"{settings.ES_INDEX_PREFIX}{index_singular}"
                    es_items = es.search(
                        index=index,
                        query={"ids": {"values": assets_key_ids[key]}},
                        fields=responder["fields"],
                    )
                    assets_key_objects[key] = (
                        []
                        if es_items["hits"]["total"]["value"] == 0
                        else responder["function"](es_items["hits"]["hits"])
                    )
                else:
                    assets_key_objects[key] = [
                        orm_schema.from_orm(asset)
                        for asset in session.query(orm_type).filter(
                            orm_type.id.in_(assets_key_ids[key])
                        )
                    ]
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return assets_key_objects
