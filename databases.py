
import oracledb
from typing import Iterable, Optional, Dict, Any


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
