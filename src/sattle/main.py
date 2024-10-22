"""The main application factory for the sattle service.

Notes
-----
Be aware that, following the normal pattern for FastAPI services, the app is
constructed when this module is loaded and is not deferred until a function is
called.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import metadata, version

from fastapi import FastAPI
from safir.dependencies.http_client import http_client_dependency
from safir.fastapi import ClientRequestError, client_request_error_handler
from safir.logging import configure_logging, configure_uvicorn_logging
from safir.middleware.x_forwarded import XForwardedMiddleware
from safir.slack.webhook import SlackRouteErrorHandler
from structlog import get_logger

from .config import config
from .handlers.external import external_router
from .handlers.internal import internal_router

__all__ = ["app"]

# The lifespan context manager is used to set up and tear down anything that
# lives for the duration of the application. This is where you would put
# database connections, etc.


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Set up and tear down the application."""
    # Any code here will be run when the application starts up.
    logger = get_logger(__name__)

    yield

    # Any code here will be run when the application shuts down.
    await http_client_dependency.aclose()

    logger.info("sattle application shut down complete.")


# The Safir library helps you set up logging around structlog,
# https://www.structlog.org/en/stable/

configure_logging(
    profile=config.profile,
    log_level=config.log_level,
    name="sattle",
)
configure_uvicorn_logging(config.log_level)

app = FastAPI(
    title="sattle",
    description=metadata("sattle")["Summary"],
    version=version("sattle"),
    openapi_url=f"{config.path_prefix}/openapi.json",
    docs_url=f"{config.path_prefix}/docs",
    redoc_url=f"{config.path_prefix}/redoc",
    lifespan=lifespan,
)
"""The main FastAPI application for sattle."""

# Attach the routers.
app.include_router(internal_router)
app.include_router(external_router, prefix=f"{config.path_prefix}")

# Add middleware.
app.add_middleware(XForwardedMiddleware)

# Add exception handler for Safir's ClientRequestError.
app.exception_handler(ClientRequestError)(client_request_error_handler)
