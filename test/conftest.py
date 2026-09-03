# The `pytester` fixture is used by the integration tests, which run a pytest of
# their own. `pytest_plugins` registers the plugin for the whole suite rather than
# just the module declaring it, so it is declared here once instead of per module.
pytest_plugins = ["pytester"]
