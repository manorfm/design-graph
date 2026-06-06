"""
Logging configuration for design-graph CLI commands.

Single entry point so both build.py and query.py configure logging
identically — level determined by --verbose / --quiet flags.

  default  → INFO   (progress messages, build summary)
  --verbose → DEBUG  (module-level diagnostics, query plans)
  --quiet   → WARNING (only warnings and errors)
"""

from __future__ import annotations

import logging


def configure_cli_logging(*, verbose: bool = False, quiet: bool = False) -> None:
    """
    Set up root logger for CLI use.

    Precedence: quiet > verbose > default (INFO).
    Format keeps messages readable without timestamps (those belong in structured logs).
    """
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s" if verbose else "%(message)s",
        force=True,  # override any previous basicConfig call
    )
    logging.getLogger("design_graph").setLevel(level)
