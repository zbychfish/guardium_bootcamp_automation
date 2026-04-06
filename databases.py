
import oracledb
import psycopg2

from typing import Iterable, Optional, Dict, Any, Tuple, Iterator


def get_oracle_conn(
    user: str,
    password: str,
    host: str,
    port: int,
    service_name: str
) -> oracledb.Connection:
    """
    Tworzy i zwraca polaczenie do Oracle (Thin mode).
    """
    dsn = f"{host}:{port}/{service_name}"
    return oracledb.connect(
        user=user,
        password=password,
        dsn=dsn
    )

def run_sql_oracle(
    conn: oracledb.Connection,
    sql: str,
    params: Optional[Dict[str, Any]] = None,
    fetch: bool = False
) -> Optional[list]:
    """
    Uruchamia SQL na Oracle.

    :param conn: otwarte polaczenie oracledb.Connection
    :param sql: zapytanie SQL
    :param params: parametry named (:param)
    :param fetch: czy zwracac wyniki (True dla SELECT)
    :return: lista wierszy lub None
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, params or {})

        if fetch:
            # Pobierz wszystkie wyniki przed zamknięciem kursora
            return cursor.fetchall()

        conn.commit()
        return None

    
def get_postgres_conn(
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str
) -> psycopg2.extensions.connection:
    """
    Tworzy i zwraca polaczenie do PostgreSQL.
    """
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password
    )


def run_sql_postgres(
    conn: psycopg2.extensions.connection,
    sql: str,
    params: Optional[Tuple | Dict[str, Any]] = None,
    fetch: bool = False
) -> Optional[Iterator[Tuple]]:
    """
    Uruchamia SQL na PostgreSQL.

    - fetch=True  -> zwraca iterator po wynikach (SELECT)
    - fetch=False -> commit (INSERT/UPDATE/DELETE/DDL)
    """

    with conn.cursor() as cursor:
        cursor.execute(sql, params)

        if fetch:
            # iterator – lazy fetch
            return cursor

        conn.commit()
        return None

