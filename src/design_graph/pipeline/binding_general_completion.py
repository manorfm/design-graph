"""Bounded general-build shape receipt, not exhaustive row authentication."""

from hashlib import sha256

from design_graph.model.graph.schema import MODEL_VERSION, node_tables, rel_tables
from design_graph.pipeline.binding_completion import canonical

MAX_ROWS = 100_000
MAX_IDENTITY_BYTES = 8 * 1024 * 1024


def rows(connection, query):
    result = connection.execute(query)
    try:
        return result.get_all()
    finally:
        result.close()


def verify_columns(connection, name, columns, key=None):
    metadata = rows(connection, f"CALL table_info('{name}') RETURN * LIMIT 128")
    expected = {
        name: "BOOL" if type_ == "BOOLEAN" else type_ for name, type_ in columns.items()
    }
    if {row[1]: row[2] for row in metadata} != expected:
        raise ValueError("incompatible general table columns: " + name)
    if key is not None and [row[1] for row in metadata if row[4]] != [key]:
        raise ValueError("incompatible general primary key: " + name)


def verify_catalog(connection):
    nodes, rels = node_tables(), rel_tables()
    expected = {name: "NODE" for name in nodes} | {name: "REL" for name in rels}
    catalog = dict(rows(connection, "CALL show_tables() RETURN name,type LIMIT 128"))
    if catalog != expected | {"BindingContextSnapshot": "NODE"}:
        raise ValueError("incomplete/incompatible general graph catalog")
    for name, table in nodes.items():
        verify_columns(connection, name, table.columns, table.key)
    for name, table in rels.items():
        verify_columns(connection, name, table.columns)
        ends = rows(connection, f"CALL show_connection('{name}') RETURN * LIMIT 2")
        if ends != [
            [
                table.source,
                table.target,
                nodes[table.source].key,
                nodes[table.target].key,
            ]
        ]:
            raise ValueError("incompatible general relationship: " + name)


def identity_receipt(connection, pattern, projection):
    count = rows(connection, f"MATCH {pattern} RETURN count(*)")[0][0]
    if count > MAX_ROWS:
        raise ValueError("general completion row budget exceeded")
    result = connection.execute(
        f"MATCH {pattern} RETURN {projection} ORDER BY {projection}"
    )
    digest, size = sha256(), 0
    try:
        while result.has_next():
            encoded = canonical(result.get_next()).encode()
            size += len(encoded)
            if size > MAX_IDENTITY_BYTES:
                raise ValueError("general completion identity budget exceeded")
            digest.update(len(encoded).to_bytes(8, "big") + encoded)
    finally:
        result.close()
    return {"count": count, "identity_sha256": digest.hexdigest()}


def general_receipt(connection):
    verify_catalog(connection)
    model = rows(connection, "MATCH (m:Model) RETURN m.version,m.capture LIMIT 2")
    if model != [[MODEL_VERSION, "html_prototype"]]:
        raise ValueError("missing/incompatible general graph model")
    nodes = node_tables()
    tables = {
        name: identity_receipt(connection, f"(n:{name})", f"n.{table.key}")
        for name, table in nodes.items()
    }
    for name, table in rel_tables().items():
        pattern = f"(a:{table.source})-[r:{name}]->(b:{table.target})"
        projection = f"a.{nodes[table.source].key},b.{nodes[table.target].key}"
        tables[name] = identity_receipt(connection, pattern, projection)
    if sum(table["count"] for table in tables.values()) > MAX_ROWS:
        raise ValueError("general completion total row budget exceeded")
    return {
        "contract": "binding-general-completion/1",
        "model": model,
        "tables": tables,
    }


def verify_general(connection, expected):
    if canonical(general_receipt(connection)) != canonical(expected):
        raise ValueError("general graph differs from completed build shape/identity")
