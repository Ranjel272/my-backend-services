import aioodbc

# Azure SQL Database config
server = 'bleupos.database.windows.net'  # Your Azure server name
database = 'POS'                         # Your Azure database name
username = 'RanjelPOS'             # Your Azure SQL admin username
password = 'Ranjel123'         # Your Azure SQL admin password
driver = 'ODBC Driver 17 for SQL Server' # This stays the same

async def get_db_connection():
    dsn = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
    )
    conn = await aioodbc.connect(dsn=dsn, autocommit=True)
    return conn
