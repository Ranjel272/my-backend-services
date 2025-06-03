# main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

# Routers
# Ensure these modules (auth.py, employee_accounts.py, discount.py)
# exist in a 'routers' subdirectory relative to this main.py file.
from routers import auth, employee_accounts, discount
# If you have a products router as well from the initial example:
# from routers import products # (Assuming products.py has a router named 'router' or similar)

app = FastAPI(
    title="My POS System API",
    description="API for managing POS operations including discounts, products, etc.",
    version="1.0.0"
)

# Include routers
# Assuming auth.py has an APIRouter instance named 'router'
app.include_router(auth.router, prefix='/auth', tags=['auth'])
# Assuming employee_accounts.py has an APIRouter instance named 'router'
app.include_router(employee_accounts.router, prefix='/employee-accounts', tags=['employee-accounts'])

# Correctly include the discount router.
# This assumes 'routers/discount.py' has an APIRouter instance named 'router_discounts'
# and that 'router_discounts' already has its prefix and tags defined.
app.include_router(discount.router_discounts)

# If you had the products router from the initial example:
# Example: assuming products.py has an APIRouter named 'router_products'
# from routers import products
# app.include_router(products.router_products)


# CORS setup
# Ensure your frontend and auth services are correctly listed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4000",      # Example React frontend
        "http://192.168.100.32:4000", # Example React frontend (local network)   # Example Auth Service for general use
        "http://localhost:9000",      # Example Auth Service used by discounts
        "http://localhost:9001",      # Another service if exists
        # Add other origins as needed
    ],
    allow_credentials=True,
    allow_methods=["*"], # Allows all methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"], # Allows all headers
)

UPLOAD_DIR_NAME = "uploads" # For file uploads if any endpoint uses it
# Ensure the 'uploads' directory exists at the same level as this main.py,
# or adjust the path accordingly.
os.makedirs(UPLOAD_DIR_NAME, exist_ok=True)
app.mount(f"/{UPLOAD_DIR_NAME}", StaticFiles(directory=UPLOAD_DIR_NAME), name=UPLOAD_DIR_NAME)

# Example simple root endpoint
@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Welcome to the POS System API. Visit /docs for API documentation."}

# Database connection lifecycle (Optional - depends on your database.py setup)
# from database import connect_db_pool, close_db_pool # Example function names
#
# @app.on_event("startup")
# async def startup_event():
#     # await connect_db_pool() # Initialize database connection pool
#     print("Application startup: Database connection pool (if used) can be initialized here.")
#
# @app.on_event("shutdown")
# async def shutdown_event():
#     # await close_db_pool() # Close database connection pool
#     print("Application shutdown: Database connection pool (if used) can be closed here.")


# Run app (this part is usually for local development)
if __name__ == "__main__":
    import uvicorn
    # The app will run on port 9002 as per your previous example
    uvicorn.run("main:app", port=9002, host="127.0.0.1", reload=True)