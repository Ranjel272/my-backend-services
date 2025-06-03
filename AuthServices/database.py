import os
import aioodbc
import pyodbc # <--- IMPORT PYODBC

# Get values from environment variables
server = os.getenv("DB_SERVER", 'bleupos.database.windows.net')
database = os.getenv("DB_NAME", 'POS')
username = os.getenv("DB_USER", 'RanjelPOS')
password = os.getenv("DB_PASSWORD, 'Ranjel123") # No default for password, should always be set
driver = os.getenv("DB_DRIVER", 'ODBC Driver 17 for SQL Server')

async def get_db_connection():
    if not password:
        # For a server application, logging an error and raising might be better
        # than printing, but for now, this helps debugging.
        print("ERROR: DB_PASSWORD environment variable not set.")
        raise ValueError("DB_PASSWORD environment variable not set.")

    dsn = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
        f"Connection Timeout=30;"
    )
    try:
        # Optional: Print DSN for debugging before connecting (mask password)
        # print(f"Attempting to connect with DSN: {dsn.replace(password, '***REDACTED***')}")
        conn = await aioodbc.connect(dsn=dsn, autocommit=True, echo=True) # Added echo=True for more verbose logs from aioodbc
        # print("Database connection successful (in get_db_connection)")
        return conn
    except pyodbc.Error as e: # <--- CHANGE HERE: CATCH pyodbc.Error
        print(f"Database connection failed. DSN used (password redacted): {dsn.replace(password, '***REDACTED***')}")
        print(f"pyodbc.Error details: {e}")
        # You can also inspect e.args for more details if needed
        # For example, e.args[0] is often the SQLSTATE
        print(f"SQLSTATE: {e.args[0] if len(e.args) > 0 else 'N/A'}")
        raise # Re-raise the exception so FastAPI startup fails clearly
    except Exception as ex: # Catch any other unexpected errors during connection
        print(f"An unexpected error occurred during database connection: {ex}")
        print(f"DSN used (password redacted): {dsn.replace(password, '***REDACTED***')}")
        raise