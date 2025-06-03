from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import logging
from pathlib import Path # Added pathlib for easier path manipulation

# Configure logging for the application
logging.basicConfig(level=logging.INFO) # You can set this to DEBUG for more verbose output
logger = logging.getLogger(__name__)

# Import your routers
# Ensure these paths are correct relative to your main.py
# This assumes 'main.py' is in the project root, and 'routers' is a subdirectory.
# Project structure example:
# your_pos_project_root/
# ├── main.py  <-- This file
# ├── routers/
# │   └── products.py
# │   └── ProductType.py
# └── pos_static_files/  <-- Directory for POS-specific static content
#     └── pos_product_images/ <-- Where POS downloaded images will be stored
try:
    from routers import ProductType, products
except ImportError as e:
    logger.error(f"Could not import routers. Ensure 'routers' directory is in PYTHONPATH or structured correctly: {e}")
    # Handle error appropriately, maybe exit or define dummy routers for testing main app structure
    ProductType = None 
    products = None


app = FastAPI(title="POS API", version="1.0.0")

# --- Static Files Setup for POS Downloaded Images ---
# Get the directory of the current script (main.py)
BASE_DIR = Path(__file__).resolve().parent # This should be your_pos_project_root

# Directory where POS will store its own static files, including downloaded product images.
# This matches the expectation from the modified `routers/products.py`:
# POS_PROJECT_ROOT_DIR / "pos_static_files" / "pos_product_images"
# where POS_PROJECT_ROOT_DIR is the parent of the 'routers' directory.
# If main.py is at the project root, then BASE_DIR is POS_PROJECT_ROOT_DIR.
POS_SPECIFIC_STATIC_ROOT_DIR = BASE_DIR / "pos_static_files"

# The sub-directory within POS_SPECIFIC_STATIC_ROOT_DIR where images are physically stored.
# This aligns with POS_UPLOAD_DIRECTORY_PHYSICAL in `routers/products.py`.
POS_DOWNLOADED_IMAGES_PHYSICAL_SUBDIR = POS_SPECIFIC_STATIC_ROOT_DIR / "pos_product_images"

# Ensure the directory for POS downloaded images exists.
if not POS_DOWNLOADED_IMAGES_PHYSICAL_SUBDIR.exists():
    try:
        POS_DOWNLOADED_IMAGES_PHYSICAL_SUBDIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created POS image directory: {POS_DOWNLOADED_IMAGES_PHYSICAL_SUBDIR}")
    except OSError as e:
        logger.error(f"Error creating POS image directory {POS_DOWNLOADED_IMAGES_PHYSICAL_SUBDIR}: {e}")
        # This could be critical if the app can't write images.
        # Consider how to handle this (e.g., raise error and exit).

# Mount the POS-specific static files directory.
# The URL prefix `/static` matches `POS_IMAGE_URL_STATIC_PREFIX` in `routers/products.py`.
# The `directory` served is `POS_SPECIFIC_STATIC_ROOT_DIR`.
# So, a file at: `your_pos_project_root/pos_static_files/pos_product_images/foo.jpg`
# will be accessible via the URL: `http://your_pos_host/static/pos_product_images/foo.jpg`
# This matches the URL construction logic in `_construct_full_url_for_pos_served_image`
# in `routers/products.py`.
try:
    app.mount(
        "/static",  # This is the `POS_IMAGE_URL_STATIC_PREFIX` from `routers/products.py`
        StaticFiles(directory=POS_SPECIFIC_STATIC_ROOT_DIR),
        name="pos_specific_static_assets"
    )
    logger.info(f"Mounted POS-specific static files from {POS_SPECIFIC_STATIC_ROOT_DIR} at /static")
except RuntimeError as e:
    logger.error(f"Failed to mount POS-specific static files: {e}. Check if directory '{POS_SPECIFIC_STATIC_ROOT_DIR}' exists and is accessible.")
    # Potentially raise the error or exit if static files are critical.


# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4000",      # Assuming your React frontend runs here
        "http://192.168.100.32:4000", # Another potential frontend origin
        "http://127.0.0.1:9000",      # Auth service (POS direct auth)
        "http://localhost:9000",       # Auth service (POS direct auth)
        "http://localhost:8000",       # IS service & IS Auth service
        "http://127.0.0.1:8000",  
             "http://127.0.0.1:8001",
                     "http://localhost:8001",       # IS service & IS Auth service

                       # IS service & IS Auth service
        "http://localhost:9001",      # This POS API itself (for self-referential or testing)
        "http://127.0.0.1:9001"       # This POS API itself
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Include Routers ---
# Assumes that the `prefix` is already defined within each router file (e.g., products.py, ProductType.py)
if products:
    app.include_router(products.router)
    logger.info(f"Included 'products' router with its internal prefix: {products.router.prefix}")
else:
    logger.warning("'products' router not loaded.")

if ProductType:
    app.include_router(ProductType.router)
    logger.info(f"Included 'ProductType' router with its internal prefix: {ProductType.router.prefix}")
else:
    logger.warning("'ProductType' router not loaded.")

logger.info("FastAPI application configured and routers included.")

# --- Root Endpoint (Optional) ---
@app.get("/")
async def read_root():
    return {"message": "Welcome to the POS API. POS-specific static files are served from /static."}

# --- Run App (for local development) ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Uvicorn server for POS API on http://127.0.0.1:9001")
    # Ensure main:app points to this file (main.py) and the FastAPI instance `app`.
    uvicorn.run("main:app", host="127.0.0.1", port=9001, reload=True)