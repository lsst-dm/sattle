"""Handlers for the app's external root, ``/sattle/``."""

from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from safir.dependencies.logger import logger_dependency
from safir.metadata import Metadata as SafirMetadata
from safir.metadata import get_metadata
from structlog.stdlib import BoundLogger

from ..config import config
from ..models import Index
#from ..dependencies.singletondependency import example_singleton_dependency
#from ..exceptions import DemoInternalError

# The APIRouter is what the individual endpoints are attached to. In main.py,
# this external_router is mounted at the path "/sattle". When we
# deploy this on Kubernetes, that "/sattle" path is available
# through an Ingress, and therefore becomes available over the internet
# (hence why we call these the external endpoints)
#
# Note the custom route class, SlackRouteErrorHandler. This is a Safir
# API that reports exceptions to a Slack channel. See Lesson 5 for more.

external_router = APIRouter()#route_class=SlackRouteErrorHandler)
"""FastAPI router for all external handlers."""


# In the default template, there's a "models" module that holds all Pydantic
# models. For this router, we're going to co-locate models and path operation
# functions in the same module to make the demo easier to follow. For a real
# application, I recommend keeping models in their own module, but instead of
# a single root-level "models" module, keep the API models next to the
# handlers, and have internal models elsewhere in the "domain" and "storage"
# interface subpackages. Keeping a separation between your API, your
# application's internal domain and storage, and models for interfacing with
# other services will make it easier to grow the codebase without
# breaking the API.


@external_router.get(
    "/",
    description=(
        "Document the top-level API here. By default it only returns metadata"
        " about the application."
    ),
    response_model=Index,
    response_model_exclude_none=True,
    summary="Application metadata",
)
async def get_index(
    logger: Annotated[BoundLogger, Depends(logger_dependency)],
) -> Index:
    """GET ``/sattle/`` (the app's external root).

    Customize this handler to return whatever the top-level resource of your
    application should return. For example, consider listing key API URLs.
    When doing so, also change or customize the response model in
    `fastapibootcamp.models.Index`.

    By convention, the root of the external API includes a field called
    ``metadata`` that provides the same Safir-generated metadata as the
    internal root endpoint.
    """
    # There is no need to log simple requests since uvicorn will do this
    # automatically, but this is included as an example of how to use the
    # logger for more complex logging.
    logger.info("Request for application metadata")

    metadata = get_metadata(
        package_name="sattle",
        application_name=config.name,
    )
    return Index(metadata=metadata)
