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


def property_receipt(connection):
    """Explicit full-property v1; legacy general_receipt semantics stay unchanged.

    Bound strings before fetching them, then total canonical bytes/rows. The
    physical JSON extension is deliberately excluded to avoid a recursive hash.
    """
    from design_graph.model.graph.source_build_ownership import (
        GeneralCommitment,
        PayloadOwner,
        TableCommitment,
    )
    shape = general_receipt(connection)
    nodes, rels = node_tables(), rel_tables()
    tables, owners, total_bytes, total_rows = [], [], 0, 0
    for name, table in list(nodes.items()) + list(rels.items()):
        is_node = name in nodes
        pattern = f'(n:{name})' if is_node else f'(a:{table.source})-[r:{name}]->(b:{table.target})'
        prefix = 'n' if is_node else 'r'
        columns = list(table.columns)
        keys = [f'n.{table.key}'] if is_node else [f'a.{nodes[table.source].key}', f'b.{nodes[table.target].key}']
        projection = keys + [f'{prefix}.{col}' for col in columns]
        strings = [f'{prefix}.{col}' for col in columns if table.columns[col] == 'STRING']
        # Aggregate preflight happens before any potentially large source fetch.
        if strings:
            sizes = ','.join(f'coalesce(sum(size({col})),0)' for col in strings)
            if sum(rows(connection, f'MATCH {pattern} RETURN {sizes}')[0]) > MAX_IDENTITY_BYTES:
                raise ValueError('general property pre-fetch character budget exceeded')
        count = shape['tables'][name]['count']
        total_rows += count
        result = connection.execute(f'MATCH {pattern} RETURN ' + ','.join(f'{expression} AS p{i}' for i, expression in enumerate(projection)))
        encoded_rows = []
        try:
            while result.has_next():
                row = result.get_next()
                encoded = canonical(row).encode()
                total_bytes += len(encoded)
                if total_bytes > MAX_IDENTITY_BYTES or total_rows > MAX_ROWS:
                    raise ValueError('general property byte/row budget exceeded')
                encoded_rows.append(encoded)
                key = canonical(row[:len(keys)])
                for col, value in zip(columns, row[len(keys):]):
                    # All STRING payloads receive document-level owner locators;
                    # never silently omit a newly delivered source-derived field.
                    if table.columns[col] == 'STRING':
                        if len(owners) >= MAX_ROWS:
                            raise ValueError('general owner locator budget exceeded')
                        owners.append(PayloadOwner(name, key, col, sha256(canonical(value).encode()).hexdigest(), sha256((value or '').encode()).hexdigest()))
        finally:
            result.close()
        digest = sha256()
        for encoded in sorted(encoded_rows):
            digest.update(len(encoded).to_bytes(8, 'big') + encoded)
        schema = canonical({'columns': table.columns, 'key': table.key} if is_node else {'columns': table.columns, 'source': table.source, 'target': table.target})
        tables.append(TableCommitment(name, schema, count, digest.hexdigest()))
    return GeneralCommitment('binding-general-properties/1', MODEL_VERSION, 'html_prototype', sha256(canonical(shape).encode()).hexdigest(), tuple(tables)), tuple(sorted(owners, key=lambda o: canonical([o.table, o.key, o.field, o.payload_sha256])))


def verify_general(connection, expected):
    if canonical(general_receipt(connection)) != canonical(expected):
        raise ValueError("general graph differs from completed build shape/identity")
