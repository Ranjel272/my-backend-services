from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import os

# Routers
from routers import auth, employee_accounts

app = FastAPI()

# Include routers
app.include_router(auth.router, prefix='/auth', tags=['auth'])
app.include_router(employee_accounts.router, prefix='/employee-accounts', tags=['employee-accounts'])

# CORS setup to allow React frontend and backend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4000",  # local dev React frontend
        "http://192.168.100.32:4000",  # local network React frontend
        "http://127.0.0.1:9001",  # backend port (if needed)
        "http://127.0.0.1:9002",  # backend port (if needed)
        "https://my-frontend-services-cazfyviw9-ranjel272s-projects.vercel.app",  # deployed Vercel frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# File uploads
UPLOAD_DIR_NAME = "uploads"
os.makedirs(UPLOAD_DIR_NAME, exist_ok=True)
app.mount(f"/{UPLOAD_DIR_NAME}", StaticFiles(directory=UPLOAD_DIR_NAME), name=UPLOAD_DIR_NAME)

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", port=9000, host="127.0.0.1", reload=True)
