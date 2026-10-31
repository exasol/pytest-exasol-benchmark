"""Shared command-line error types."""

import click


class _CommandError(click.ClickException):
    """A command could not be done, for example because of invalid input."""

    exit_code = 2
