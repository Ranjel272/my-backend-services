import os
import aioodbc

# Get values from environment variables
# Provide default values for local development if you want, or let it fail if not set
server = os.getenv("DB_SERVER", 'bleupos.database.windows.net')
database = os.getenv("DB_NAME", 'POS')
username = os.getenv("DB_USER", 'RanjelPOS')
password = os.getenv("DB_PASSWORD") # No default for password, should always be set
driver = os.getenv("DB_DRIVER", 'ODBC Driver 17 for SQL Server')

async def get_db_connection():
    if not password:
        raise ValueError("DB_PASSWORD environment variable not set.")

    dsn = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
        f"Connection Timeout=30;" # Optional: Add a connection timeout
    )
    try:
        conn = await aioodbc.connect(dsn=dsn, autocommit=True)
        return conn
    except aioodbc.Error as e:
        print(f"Database connection failed. DSN used (password redacted): {dsn.replace(password, '***REDACTED***')}")
        print(f"Error: {e}")
        raise # Re-raise the exception so FastAPI startup fails clearly