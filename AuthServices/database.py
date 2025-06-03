import aioodbc

server = 'bleupos.database.windows.net'
database = 'POS'
username = 'RanjelPOS'
password = 'Ranjel123'
driver = 'ODBC Driver 17 for SQL Server'

async def get_db_connection():
    dsn = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
    )
    conn = await aioodbc.connect(dsn=dsn, autocommit=True)
    return conn
