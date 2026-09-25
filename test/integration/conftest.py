import pytest
from exasol.pytest_backend import (
    BACKEND_ONPREM,
    BACKEND_OPTION,
    BACKEND_SAAS,
)


@pytest.fixture(scope="session")
def backend_args(
    backend,
    backend_aware_database_params,
    exasol_config,
    bucketfs_config,
    ssh_config,
    backend_aware_saas_database_id,
) -> list[str]:
    """
    Returns the command line arguments for a pytester run against the database of
    the current backend.

    Every pytester run is a pytest session of its own, which would start a new
    database. Instead, the database is created once by the outer session, see
    `backend_aware_database_params`, and the pytester runs attach to it: onprem as an
    external database, SaaS by its database ID.
    """
    if backend == BACKEND_ONPREM:
        return [
            BACKEND_OPTION,
            BACKEND_ONPREM,
            "--itde-db-version",
            "external",
            "--exasol-host",
            exasol_config.host,
            "--exasol-port",
            str(exasol_config.port),
            "--exasol-username",
            exasol_config.username,
            "--exasol-password",
            exasol_config.password,
            "--bucketfs-url",
            bucketfs_config.url,
            "--bucketfs-username",
            bucketfs_config.username,
            "--bucketfs-password",
            bucketfs_config.password,
            "--ssh-port",
            str(ssh_config.port),
        ]
    if backend == BACKEND_SAAS:
        return [
            BACKEND_OPTION,
            BACKEND_SAAS,
            "--saas-database-id",
            backend_aware_saas_database_id,
        ]
    raise ValueError(f"Unknown backend {backend}")
