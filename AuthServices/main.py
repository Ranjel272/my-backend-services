from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

# Routers
from routers import auth, employee_accounts

app = FastAPI()

# Include routers
app.include_router(auth.router, prefix='/auth', tags=['auth'])
app.include_router(employee_accounts.router, prefix='/employee-accounts', tags=['employee-accounts'])

# CORS setup to allow React frontend and other backends to communicate with this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4000",            # React frontend (local dev)
        "http://192.168.100.32:4000",       # React frontend (local network)
        "http://127.0.0.1:9001",            # Another backend (if any)
        "http://127.0.0.1:9002",            # Another backend (if any)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded files from /uploads
UPLOAD_DIR_NAME = "uploads"
os.makedirs(UPLOAD_DIR_NAME, exist_ok=True)  # Ensure the directory exists
app.mount(f"/{UPLOAD_DIR_NAME}", StaticFiles(directory=UPLOAD_DIR_NAME), name=UPLOAD_DIR_NAME)

# Run app (development only)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=9000, reload=True)
