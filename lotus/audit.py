import json
from lotus.db import connection, init_db


def log(action, object_type, object_id, details=None, actor="Аналитик", path=None):
    init_db(path)
    with connection(path) as con:
        con.execute("INSERT INTO audit_log(actor,action,object_type,object_id,details) VALUES (?,?,?,?,?)",
                    (actor, action, object_type, object_id, json.dumps(details or {}, ensure_ascii=False)))


def read_log(path=None):
    init_db(path)
    with connection(path) as con:
        return [dict(row) for row in con.execute("SELECT * FROM audit_log ORDER BY id DESC")]
