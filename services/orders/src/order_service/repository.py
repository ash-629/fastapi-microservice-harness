# 每次调用独立连接，短事务，禁止网络期间持锁。
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def now():
    return datetime.now(UTC).isoformat()


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=0.5)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(path, sql):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript(sql)
