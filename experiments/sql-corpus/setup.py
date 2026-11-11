"""Create the shared corpus dataset on one engine. The rows are written once, below; each engine gets its own DDL.

  python -I setup.py postgres "host=... port=... user=... password=... dbname=corpus"
  python -I setup.py arcadedb http://HOST:HTTP_PORT PASSWORD

PostgreSQL gets tables with primary and foreign keys. ArcadeDB gets what its own SQL offers today: vertex types for
person and company, an edge type for knows, a document type for typed, and company_id kept as a plain property. Nothing
here is measured. The script exits non-zero unless the row counts match the dataset, so an empty run fails loudly.
"""
import base64
import json
import sys
import urllib.request

COMPANIES = [(1, "Acme", "NL"), (2, "Beta", "KR"), (3, "Gamma", "NL")]  # Gamma has no persons
PERSONS = [  # id, name, age, company_id (None: no company, so an unmatched LEFT JOIN has rows to keep)
    (1, "Ada", 36, 1), (2, "Bo", 29, 1), (3, "Cy", 41, 2), (4, "Di", 25, None), (5, "Ed", 33, 2), (6, "Flo", 52, None),
]
KNOWS = [  # id, source_id, target_id, since; edges 1 and 2 are parallel (the same pair twice)
    (1, 1, 2, 2019), (2, 1, 2, 2021), (3, 2, 3, 2020), (4, 3, 1, 2018), (5, 1, 4, 2022), (6, 5, 6, 2023),
]
TYPED = [  # i, big (beyond 2**53), n, f, b, s, d (ISO date); the last row is all NULL
    (1, 9007199254740993, "12345.67", 2.5, True, "héllo", "2026-11-11"),
    (2, -1, "0.10", -0.5, False, "", "1970-01-01"),
    (3, None, None, None, None, None, None),
]
COUNTS = {"company": len(COMPANIES), "person": len(PERSONS), "knows": len(KNOWS), "typed": len(TYPED)}

PG_DDL = [
    "DROP TABLE IF EXISTS knows, person, company, typed CASCADE",
    "CREATE TABLE company (id bigint PRIMARY KEY, name text NOT NULL, country text NOT NULL)",
    "CREATE TABLE person (id bigint PRIMARY KEY, name text NOT NULL, age integer NOT NULL,"
    " company_id bigint REFERENCES company (id))",
    "CREATE TABLE knows (id bigint PRIMARY KEY, source_id bigint NOT NULL REFERENCES person (id),"
    " target_id bigint NOT NULL REFERENCES person (id), since integer NOT NULL)",
    "CREATE TABLE typed (i integer PRIMARY KEY, big bigint, n numeric(10,2), f double precision, b boolean, s text,"
    " d date)",
]

ADB_DDL = [
    "CREATE VERTEX TYPE company", "CREATE PROPERTY company.id LONG", "CREATE PROPERTY company.name STRING",
    "CREATE PROPERTY company.country STRING", "CREATE INDEX ON company (id) UNIQUE",
    "CREATE VERTEX TYPE person", "CREATE PROPERTY person.id LONG", "CREATE PROPERTY person.name STRING",
    "CREATE PROPERTY person.age INTEGER", "CREATE PROPERTY person.company_id LONG",
    "CREATE INDEX ON person (id) UNIQUE",
    "CREATE EDGE TYPE knows", "CREATE PROPERTY knows.id LONG", "CREATE PROPERTY knows.since INTEGER",
    "CREATE DOCUMENT TYPE typed", "CREATE PROPERTY typed.i INTEGER", "CREATE PROPERTY typed.big LONG",
    "CREATE PROPERTY typed.n DECIMAL", "CREATE PROPERTY typed.f DOUBLE", "CREATE PROPERTY typed.b BOOLEAN",
    "CREATE PROPERTY typed.s STRING", "CREATE PROPERTY typed.d DATE", "CREATE INDEX ON typed (i) UNIQUE",
]


def setup_postgres(dsn):
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as conn:
        cur = conn.cursor()
        for stmt in PG_DDL:
            cur.execute(stmt)
        cur.executemany("INSERT INTO company VALUES (%s, %s, %s)", COMPANIES)
        cur.executemany("INSERT INTO person VALUES (%s, %s, %s, %s)", PERSONS)
        cur.executemany("INSERT INTO knows VALUES (%s, %s, %s, %s)", KNOWS)
        cur.executemany("INSERT INTO typed VALUES (%s, %s, %s, %s, %s, %s, %s)", TYPED)
        return {t: cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in COUNTS}


def setup_arcadedb(url, password, database="corpus"):
    auth = "Basic " + base64.b64encode(f"root:{password}".encode()).decode()

    def post(command, params=None, language="sql"):
        body = {"language": language, "command": command}
        if params:
            body["params"] = params
        req = urllib.request.Request(f"{url}/api/v1/command/{database}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": auth})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)

    for stmt in ADB_DDL:
        post(stmt)
    for cid, name, country in COMPANIES:
        post("INSERT INTO company SET id = :id, name = :name, country = :country",
             {"id": cid, "name": name, "country": country})
    for pid, name, age, cid in PERSONS:
        post("INSERT INTO person SET id = :id, name = :name, age = :age" + (", company_id = :cid" if cid else ""),
             {"id": pid, "name": name, "age": age, "cid": cid})
    for eid, src, tgt, since in KNOWS:
        post("CREATE EDGE knows FROM (SELECT FROM person WHERE id = :src) TO (SELECT FROM person WHERE id = :tgt)"
             " SET id = :id, since = :since", {"src": src, "tgt": tgt, "id": eid, "since": since})
    for i, big, n, f, b, s, d in TYPED:
        if big is None:
            post("INSERT INTO typed SET i = :i", {"i": i})
        else:
            post("INSERT INTO typed SET i = :i, big = :big, n = :n, f = :f, b = :b, s = :s, d = date(:d, 'yyyy-MM-dd')",
                 {"i": i, "big": big, "n": n, "f": f, "b": b, "s": s, "d": d})
    return {t: post(f"SELECT count(*) AS n FROM {t}")["result"][0]["n"] for t in COUNTS}


def main(argv):
    if len(argv) < 2 or argv[0] not in ("postgres", "arcadedb") or (argv[0] == "arcadedb" and len(argv) != 3):
        sys.exit(__doc__)
    counts = setup_postgres(argv[1]) if argv[0] == "postgres" else setup_arcadedb(argv[1], argv[2])
    print(json.dumps({"engine": argv[0], "counts": counts}))
    sys.exit(0 if counts == COUNTS else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
