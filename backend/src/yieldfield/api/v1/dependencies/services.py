"""Composition of 3A adapters for request handling (spec §5.1) — the only place API code
builds repositories, the cipher, or the registration service. Routers consume the
Annotated aliases and never import infrastructure themselves.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from yieldfield.api.v1.dependencies.database import DbSession
from yieldfield.api.v1.dependencies.settings import SettingsDep
from yieldfield.api.v1.schemas.jobs import JobStatusRead
from yieldfield.config.settings import Settings
from yieldfield.infrastructure.connectors.registration import ConnectorRegistrationService
from yieldfield.infrastructure.persistence.job import Job
from yieldfield.infrastructure.persistence.repositories import (
    SqlAlchemyConnectorRepository,
    SqlAlchemyFindingRepository,
    SqlAlchemyJobRepository,
    SqlAlchemyReconciliationRepository,
)
from yieldfield.infrastructure.security.credential_cipher import (
    CredentialCipherError,
    FernetCredentialCipher,
)


def get_job_repository(session: DbSession) -> SqlAlchemyJobRepository:
    return SqlAlchemyJobRepository(session)


def get_connector_store(session: DbSession) -> SqlAlchemyConnectorRepository:
    return SqlAlchemyConnectorRepository(session)


def get_finding_repository(session: DbSession) -> SqlAlchemyFindingRepository:
    return SqlAlchemyFindingRepository(session)


def get_reconciliation_repository(session: DbSession) -> SqlAlchemyReconciliationRepository:
    return SqlAlchemyReconciliationRepository(session)


def _cipher(settings: Settings) -> FernetCredentialCipher:
    if not settings.credentials_key:
        raise CredentialCipherError(
            "YIELDFIELD_CREDENTIALS_KEY is required to register or use connectors (§16)."
        )
    return FernetCredentialCipher(settings.credentials_key)


def get_registration_service(
    session: DbSession, settings: SettingsDep
) -> ConnectorRegistrationService:
    return ConnectorRegistrationService(
        SqlAlchemyConnectorRepository(session),
        _cipher(settings),
        base_url=settings.connector_base_url,
    )


JobRepo = Annotated[SqlAlchemyJobRepository, Depends(get_job_repository)]
ConnectorStoreDep = Annotated[SqlAlchemyConnectorRepository, Depends(get_connector_store)]
FindingRepo = Annotated[SqlAlchemyFindingRepository, Depends(get_finding_repository)]
ReconciliationRepo = Annotated[
    SqlAlchemyReconciliationRepository, Depends(get_reconciliation_repository)
]
RegistrationDep = Annotated[ConnectorRegistrationService, Depends(get_registration_service)]


def job_status_read(job: Job) -> JobStatusRead:
    """Map the infrastructure Job onto the DTO here so routers never import infrastructure."""
    return JobStatusRead(
        job_id=job.id,
        job_type=job.job_type.value,
        status=job.status.value,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
        result_type=job.result_type.value if job.result_type is not None else None,
        result_ref=job.result_ref,
    )
