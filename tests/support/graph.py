"""A graph writer and a reader over the same connection, for tests that read what they just wrote."""

from __future__ import annotations

from types import SimpleNamespace

import kuzu

from design_graph.model.graph.reader import GraphReader
from design_graph.model.graph.writer import GraphWriter


class ReaderAfterCommit:
    """A GraphReader that commits its writer before the first read — the writer commits once."""

    def __init__(self, reader: GraphReader, writer: GraphWriter) -> None:
        self._reader, self._writer = reader, writer

    def __getattr__(self, name: str):
        self._writer.commit()
        return getattr(self._reader, name)


def writer_and_reader(conn: kuzu.Connection) -> SimpleNamespace:
    writer = GraphWriter(conn)
    return SimpleNamespace(writer=writer, reader=ReaderAfterCommit(GraphReader(conn), writer), conn=conn)
