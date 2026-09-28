.. _developer_guide:

:octicon:`tools` Developer Guide
================================


Integration Tests
-----------------

The integration tests use the plugin `pytest-exasol-backend
<https://github.com/exasol/pytest-backend>`_ for the database, so its options
select the backend, for example ``--backend=onprem``, and configure the database. The
CI runs the integration tests with ``--backend=onprem``.

Sharing the Database
^^^^^^^^^^^^^^^^^^^^

Most integration tests verify the plugin by running a pytest session of their own with
the ``pytester`` fixture. As pytest-exasol-backend creates a database per session,
each of these inner sessions would create a new database, and the total time of the
integration tests would grow with every test.

Instead, the database is created once by the outer session and shared by all inner
sessions:

* A test requests the fixture ``backend_args``, see ``test/integration/conftest.py``.
  The fixture depends on ``backend_aware_database_params``, so the outer session
  creates the database of the selected backend and waits until it is ready. The fixture
  also depends on the fixture ``backend`` of pytest-exasol-backend, which is
  parametrized over the backends. So
  the test is reported per backend and skipped for a backend which is not selected.
* The test passes ``backend_args`` to the inner session with
  ``pytester.runpytest(*backend_args)``. The arguments select the current backend and
  attach to the database of the outer session instead of creating a new one: for
  ``onprem`` as an external database with ``--itde-db-version external`` and the
  connection options of the outer session, for ``saas`` with ``--saas-database-id``.

As all tests share the same database, each test has to use schema names of its own
and clean up the objects it creates.
