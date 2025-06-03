import aioodbc

# database config
server = 'LAPTOP-8KPHOHE5\\SQLEXPRESS'
database = 'POS'
username = 'RanjelPOS'
password = 'Ranjel123'
driver = 'ODBC Driver 17 for SQL Server'

# async function to get db connection
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