from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from typing import List, Optional
import httpx
from database import get_db_connection # Make sure this import points to your actual db connection module
import logging
import os # Added
import uuid # Added
from pathlib import Path # Added

logger = logging.getLogger(__name__)

# --- POS Configuration for Image Handling ---
# This assumes your products.py file is inside a 'routers' directory,
# and 'pos_static_files' is at the same level as the 'routers' directory.
# Adjust POS_ROUTER_BASE_DIR if your project structure is different.
# Example structure:
# project_root/
# ├── main.py
# ├── routers/
# │   └── products.py  <-- This file
# └── pos_static_files/
#     └── pos_product_images/

try:
    POS_ROUTER_FILE_DIR = Path(__file__).resolve().parent
    POS_PROJECT_ROOT_DIR = POS_ROUTER_FILE_DIR.parent # Assumes products.py is in 'routers'
except NameError: # __file__ is not defined if running in an interactive interpreter directly
    POS_PROJECT_ROOT_DIR = Path(".").resolve() # Fallback for some environments, might need adjustment

POS_UPLOAD_DIRECTORY_PHYSICAL = POS_PROJECT_ROOT_DIR / "pos_static_files" / "pos_product_images"
POS_UPLOAD_DIRECTORY_PHYSICAL.mkdir(parents=True, exist_ok=True)
logger.info(f"POS: Physical image upload directory: {POS_UPLOAD_DIRECTORY_PHYSICAL}")


# Path segment stored in the POS DB for images.
# This part of the path will be appended to the static files URL prefix.
# e.g., if static URL is /pos_static, and DB stores /pos_product_images/img.jpg
# then full URL is /pos_static/pos_product_images/img.jpg
POS_IMAGE_DB_PATH_SEGMENT = "/pos_product_images"

# This is the URL prefix under which your POS FastAPI app serves its static files.
# This needs to match how you mount StaticFiles in your POS main.py.
# From your POS main.py, it seems you mount at "/static".
POS_IMAGE_URL_STATIC_PREFIX = "/static"


# --- Auth Schemes for POS --- (Keep as is)
oauth2_scheme_from_is = OAuth2PasswordBearer(
    tokenUrl="http://localhost:8000/auth/token",
    scheme_name="OAuth2PasswordBearerForISCalls"
)
oauth2_scheme_direct_pos = OAuth2PasswordBearer(
    tokenUrl="http://localhost:9000/auth/token",
    scheme_name="OAuth2PasswordBearerForDirectPOSAccess"
)

# --- Auth Validation Functions for POS --- (Keep as is)
async def validate_token_and_roles_is_caller(token: str, allowed_roles: List[str]):
    auth_url = "http://localhost:8000/auth/users/me"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(auth_url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            error_detail = f"POS: Auth service (for IS token @ {auth_url}) error: {e.response.status_code}"
            try: error_detail += f" - {e.response.json().get('detail', e.response.text)}"
            except: error_detail += f" - {e.response.text}"
            logger.error(error_detail)
            raise HTTPException(status_code=e.response.status_code, detail=error_detail)
        except httpx.RequestError as e:
            logger.error(f"POS: Could not connect to auth service (for IS token @ {auth_url}): {str(e)}")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"POS: Auth service unavailable: {e}")
    user_data = response.json()
    user_role = user_data.get("userRole")
    if user_role not in allowed_roles:
        logger.warning(f"POS: Access denied for IS caller role '{user_role}'. Allowed: {allowed_roles}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="POS: Access denied. Calling service/user does not have the required role.")
    return user_data

async def validate_token_and_roles_direct_pos_caller(token: str, allowed_roles: List[str]):
    auth_url = "http://localhost:9000/auth/users/me"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(auth_url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            error_detail = f"POS: Auth service (direct @ {auth_url}) error: {e.response.status_code}"
            try: error_detail += f" - {e.response.json().get('detail', e.response.text)}"
            except: error_detail += f" - {e.response.text}"
            logger.error(error_detail)
            raise HTTPException(status_code=e.response.status_code, detail=error_detail)
        except httpx.RequestError as e:
            logger.error(f"POS: Could not connect to POS auth service (direct @ {auth_url}): {str(e)}")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"POS: Auth service unavailable: {e}")
    user_data = response.json()
    user_role = user_data.get("userRole")
    if user_role not in allowed_roles:
        logger.warning(f"POS: Access denied for direct caller role '{user_role}'. Allowed: {allowed_roles}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="POS: Access denied (direct POS access). User does not have the required role.")
    return user_data

router = APIRouter(prefix="/Products", tags=["POS Products"])

# --- POS Helper Function for Image Handling ---
async def _download_and_save_image_from_is(
    image_url_from_is: Optional[str],
    current_pos_db_image_path: Optional[str] = None
) -> Optional[str]:
    """
    Downloads an image from the IS URL, saves it locally in POS, and returns the new POS DB path.
    Deletes the old POS local image if current_pos_db_image_path is provided and different.
    The returned path is like "/pos_product_images/filename.jpg".
    """
    new_pos_db_image_path_segment = None

    # 1. Handle deletion of old image
    if current_pos_db_image_path: # current_pos_db_image_path is like "/pos_product_images/old.jpg"
        old_filename = Path(current_pos_db_image_path).name
        old_physical_file = POS_UPLOAD_DIRECTORY_PHYSICAL / old_filename
        
        # Delete if no new image URL, or if new URL is different (implies new image or removal)
        if not image_url_from_is or (image_url_from_is and current_pos_db_image_path != image_url_from_is): # Simplified check
            if old_physical_file.exists():
                try:
                    os.remove(old_physical_file)
                    logger.info(f"POS: Deleted old image file: {old_physical_file}")
                except OSError as e:
                    logger.error(f"POS: Error deleting old image file {old_physical_file}: {e}")
            if not image_url_from_is:
                return None # No new image, old one deleted (if existed), return None

    if not image_url_from_is:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(image_url_from_is)
            response.raise_for_status()

        image_content = response.content
        content_type = response.headers.get("content-type", "").lower()

        if not content_type.startswith("image/"):
            logger.warning(f"POS: URL {image_url_from_is} did not return an image. Content-Type: {content_type}. Proceeding without image.")
            return None # Or raise if image is mandatory

        original_filename_from_url = Path(image_url_from_is).name
        original_ext = Path(original_filename_from_url).suffix.lower()
        if not original_ext or original_ext == ".":
            if "jpeg" in content_type or "jpg" in content_type: original_ext = ".jpg"
            elif "png" in content_type: original_ext = ".png"
            # Add more types if needed
            else: original_ext = ".jpg"

        unique_filename = f"{uuid.uuid4()}{original_ext}"
        physical_file_loc = POS_UPLOAD_DIRECTORY_PHYSICAL / unique_filename

        with open(physical_file_loc, "wb") as f:
            f.write(image_content)
        
        new_pos_db_image_path_segment = f"{POS_IMAGE_DB_PATH_SEGMENT}/{unique_filename}" # e.g., "/pos_product_images/uuid.jpg"
        logger.info(f"POS: Downloaded image from {image_url_from_is} to {physical_file_loc}. Storing DB path: {new_pos_db_image_path_segment}")

    except httpx.HTTPStatusError as e:
        logger.error(f"POS: HTTP error downloading image from {image_url_from_is}: {e.response.status_code}. Detail: {e.response.text}")
        return None # Failed to download, return None (product will have no image or keep old one if not deleted)
    except httpx.RequestError as e:
        logger.error(f"POS: Network error downloading image from {image_url_from_is}: {e}")
        return None
    except IOError as e:
        logger.error(f"POS: IO error saving image downloaded from {image_url_from_is}: {e}")
        return None
    except Exception as e:
        logger.error(f"POS: Unexpected error processing image from {image_url_from_is}: {e}", exc_info=True)
        return None

    return new_pos_db_image_path_segment


def _construct_full_url_for_pos_served_image(pos_db_image_path_segment: Optional[str]) -> Optional[str]:
    """
    Constructs the full public URL for an image served by this POS system.
    Example: pos_db_image_path_segment = "/pos_product_images/image.jpg"
             POS_IMAGE_URL_STATIC_PREFIX = "/static"
             Result: "/static/pos_product_images/image.jpg"
    """
    if pos_db_image_path_segment and pos_db_image_path_segment.startswith(POS_IMAGE_DB_PATH_SEGMENT):
        return f"{POS_IMAGE_URL_STATIC_PREFIX}{pos_db_image_path_segment}"
    return pos_db_image_path_segment # Or None if it's not a valid POS path

# --- POS Models --- (Updated comments for ProductImage)
class PosProductCreate(BaseModel):
    ProductName: str
    ProductTypeName: str
    ProductCategory: str
    ProductDescription: Optional[str] = None
    ProductPrice: float
    ProductImage: Optional[str] = None # EXPECTS: Full HTTP URL from IS (e.g., http://is-server/static/img.jpg)
    ProductSize: Optional[str] = None

class PosProductUpdate(BaseModel):
    ProductName: str
    ProductTypeName: str
    ProductCategory: str
    ProductDescription: Optional[str] = None
    ProductPrice: float
    ProductImage: Optional[str] = None # EXPECTS: Full HTTP URL from IS
    ProductSize: Optional[str] = None

class PosProductOut(BaseModel):
    ProductID: int
    ProductName: str
    ProductTypeID: int
    ProductCategory: str
    ProductDescription: Optional[str] = None
    ProductPrice: float
    ProductImage: Optional[str] = None # OUTPUTS: POS-served URL (e.g., /static/pos_product_images/img.jpg)
    ProductSize: Optional[str] = None

class PosProductGet(BaseModel):
    ProductID: int
    ProductName: str
    ProductTypeID: int
    ProductTypeName: str
    ProductCategory: str
    ProductDescription: Optional[str] = None
    ProductPrice: float
    ProductImage: Optional[str] = None # OUTPUTS: POS-served URL
    ProductSizes: Optional[List[str]] = None

# (Other models: PosSizeCreate, PosProductSizeOut, PosAddSizeByProductNamePayload - unchanged)
class PosSizeCreate(BaseModel):
    SizeName: str

class PosProductSizeOut(BaseModel):
    SizeID: int
    ProductID: int
    SizeName: str

class PosAddSizeByProductNamePayload(BaseModel):
    ProductName: str
    SizeName: str


# --- POS Endpoints ---

@router.get("/products/", response_model=List[PosProductGet])
async def get_all_pos_products(token: str = Depends(oauth2_scheme_direct_pos)):
    # (Auth and DB connection logic remains the same)
    await validate_token_and_roles_direct_pos_caller(token, ["admin", "manager", "staff"])
    conn = None
    try:
        conn = await get_db_connection()
        async with conn.cursor() as cursor:
            await cursor.execute("""
                SELECT p.ProductID, p.ProductName, p.ProductTypeID, pt.ProductTypeName,
                       p.ProductCategory, p.ProductDescription, p.ProductPrice, p.ProductImage
                FROM Products p
                LEFT JOIN ProductType pt ON p.ProductTypeID = pt.ProductTypeID
                ORDER BY p.ProductName
            """)
            product_rows = await cursor.fetchall()
            if not product_rows: return []

            products_out_list = []
            # ... (size fetching logic remains the same) ...
            product_ids = [r.ProductID for r in product_rows]
            sizes_by_product_id = {}
            if product_ids:
                placeholders = ','.join(['?'] * len(product_ids))
                size_query = f"SELECT ProductID, SizeName FROM Size WHERE ProductID IN ({placeholders}) ORDER BY SizeName"
                await cursor.execute(size_query, *product_ids)
                size_rows_db = await cursor.fetchall()
                for sr in size_rows_db:
                    sizes_by_product_id.setdefault(sr.ProductID, []).append(sr.SizeName)

            for r in product_rows:
                products_out_list.append(PosProductGet(
                    ProductID=r.ProductID,
                    ProductName=r.ProductName,
                    ProductTypeID=r.ProductTypeID,
                    ProductTypeName=r.ProductTypeName or "N/A",
                    ProductCategory=r.ProductCategory,
                    ProductDescription=r.ProductDescription,
                    ProductPrice=float(r.ProductPrice or 0.0),
                    ProductImage=_construct_full_url_for_pos_served_image(r.ProductImage), # MODIFIED
                    ProductSizes=sizes_by_product_id.get(r.ProductID)
                ))
            return products_out_list
    except Exception as e:
        logger.error(f"POS: Error in get_all_pos_products: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="POS: Error fetching products.")
    finally:
        if conn: await conn.close()

@router.post("/products/", response_model=PosProductOut, status_code=status.HTTP_201_CREATED)
async def add_product_to_pos(product_payload: PosProductCreate, token: str = Depends(oauth2_scheme_from_is)):
    await validate_token_and_roles_is_caller(token, ["admin", "manager", "staff"])
    conn = None
    new_product_id: Optional[int] = None
    processed_size_for_response: Optional[str] = None
    pos_db_image_path_segment_to_store: Optional[str] = None

    try:
        # Download image from IS if URL is provided
        if product_payload.ProductImage:
            logger.info(f"POS: Received ProductImage URL from IS for new product: {product_payload.ProductImage}")
            pos_db_image_path_segment_to_store = await _download_and_save_image_from_is(product_payload.ProductImage)
            if pos_db_image_path_segment_to_store:
                logger.info(f"POS: Image downloaded. DB path to store: {pos_db_image_path_segment_to_store}")
            else:
                logger.warning(f"POS: Failed to download/save image from {product_payload.ProductImage}. Proceeding without image.")
        
        conn = await get_db_connection()
        async with conn.cursor() as cursor:
            # ... (product type and name conflict check remains the same) ...
            await cursor.execute("SELECT productTypeID FROM dbo.ProductType WHERE productTypeName = ?", product_payload.ProductTypeName)
            type_row = await cursor.fetchone()
            if not type_row:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"POS: ProductTypeName '{product_payload.ProductTypeName}' not found.")
            pos_product_type_id = type_row.productTypeID

            await cursor.execute("SELECT ProductID FROM Products WHERE ProductName COLLATE Latin1_General_CI_AS = ?", product_payload.ProductName)
            if await cursor.fetchone():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"POS: Product name '{product_payload.ProductName}' already exists.")

            await cursor.execute("""
                INSERT INTO Products (ProductName, ProductTypeID, ProductCategory, ProductDescription, ProductPrice, ProductImage)
                OUTPUT INSERTED.ProductID VALUES (?, ?, ?, ?, ?, ?)
            """, product_payload.ProductName, pos_product_type_id, product_payload.ProductCategory,
                 product_payload.ProductDescription, product_payload.ProductPrice, 
                 pos_db_image_path_segment_to_store) # MODIFIED: Use locally stored path
            id_row = await cursor.fetchone()
            if not id_row or not id_row.ProductID:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="POS: Failed to create product.")
            new_product_id = id_row.ProductID

            # ... (size handling remains the same) ...
            if product_payload.ProductSize and product_payload.ProductSize.strip() and new_product_id is not None:
                trimmed_size = product_payload.ProductSize.strip()
                # Check if size already exists (shouldn't for a new product, but good practice)
                await cursor.execute("SELECT SizeID FROM Size WHERE ProductID = ? AND SizeName COLLATE Latin1_General_CI_AS = ?", new_product_id, trimmed_size)
                if not await cursor.fetchone():
                    await cursor.execute("INSERT INTO Size (ProductID, SizeName) VALUES (?, ?)", new_product_id, trimmed_size)
                processed_size_for_response = trimmed_size
            
            await cursor.execute("""
                SELECT ProductID, ProductName, ProductTypeID, ProductCategory, ProductDescription, ProductPrice, ProductImage
                FROM Products WHERE ProductID = ?
            """, new_product_id)
            created_product_row = await cursor.fetchone()
            if not created_product_row:
                 raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="POS: Failed to fetch created product details.")

            return PosProductOut(
                ProductID=created_product_row.ProductID, ProductName=created_product_row.ProductName,
                ProductTypeID=created_product_row.ProductTypeID, ProductCategory=created_product_row.ProductCategory,
                ProductDescription=created_product_row.ProductDescription,
                ProductPrice=float(created_product_row.ProductPrice or 0.0),
                ProductImage=_construct_full_url_for_pos_served_image(created_product_row.ProductImage), # MODIFIED
                ProductSize=processed_size_for_response
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POS: Error in add_product_to_pos: {e}", exc_info=True)
        # Cleanup downloaded image if DB operation failed
        if pos_db_image_path_segment_to_store and new_product_id is None:
            filename_to_delete = Path(pos_db_image_path_segment_to_store).name
            physical_file_to_clean = POS_UPLOAD_DIRECTORY_PHYSICAL / filename_to_delete
            if physical_file_to_clean.exists():
                try: os.remove(physical_file_to_clean); logger.info(f"POS: Cleaned up image {physical_file_to_clean} due to product creation error.")
                except OSError as ose: logger.error(f"POS: Error cleaning up image {physical_file_to_clean}: {ose}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="POS: Error adding product.")
    finally:
        if conn: await conn.close()


@router.put("/products/{product_id}", response_model=PosProductOut)
async def update_product_in_pos(product_id: int, product_payload: PosProductUpdate, token: str = Depends(oauth2_scheme_from_is)):
    await validate_token_and_roles_is_caller(token, ["admin", "manager", "staff"])
    conn = None
    processed_size_for_response: Optional[str] = None
    pos_db_image_path_segment_for_update: Optional[str] = None

    try:
        conn = await get_db_connection()
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT ProductImage FROM Products WHERE ProductID = ?", product_id) # Get current image path
            current_product_db_row = await cursor.fetchone()
            if not current_product_db_row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"POS: Product with ID {product_id} not found.")
            
            current_pos_db_image_path = current_product_db_row.ProductImage
            logger.info(f"POS: Updating product {product_id}. Current DB image path: {current_pos_db_image_path}")
            logger.info(f"POS: Received ProductImage URL from IS for update: {product_payload.ProductImage}")

            # Download/update image if URL is provided or changed.
            # This will also handle deleting the old POS image if the new URL is different or None.
            pos_db_image_path_segment_for_update = await _download_and_save_image_from_is(
                product_payload.ProductImage,
                current_pos_db_image_path
            )
            if pos_db_image_path_segment_for_update != current_pos_db_image_path: # Log if path changed
                 logger.info(f"POS: Image path for DB update: {pos_db_image_path_segment_for_update} (was: {current_pos_db_image_path})")


            # ... (product type and name conflict check remains the same) ...
            await cursor.execute("SELECT productTypeID FROM dbo.ProductType WHERE productTypeName = ?", product_payload.ProductTypeName)
            type_row = await cursor.fetchone()
            if not type_row:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"POS: ProductTypeName '{product_payload.ProductTypeName}' not found for update.")
            pos_product_type_id = type_row.productTypeID

            await cursor.execute("SELECT 1 FROM Products WHERE ProductName COLLATE Latin1_General_CI_AS = ? AND ProductID != ?", product_payload.ProductName, product_id)
            if await cursor.fetchone():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="POS: Product name already exists for another product.")


            await cursor.execute("""
                UPDATE Products SET ProductName = ?, ProductTypeID = ?, ProductCategory = ?,
                ProductDescription = ?, ProductPrice = ?, ProductImage = ? WHERE ProductID = ?
            """, product_payload.ProductName, pos_product_type_id, product_payload.ProductCategory, 
                 product_payload.ProductDescription, product_payload.ProductPrice, 
                 pos_db_image_path_segment_for_update, product_id) # MODIFIED: Use new/updated local path

            # ... (size handling remains the same) ...
            await cursor.execute("DELETE FROM Size WHERE ProductID = ?", product_id)
            if product_payload.ProductSize and product_payload.ProductSize.strip():
                trimmed_size = product_payload.ProductSize.strip()
                await cursor.execute("INSERT INTO Size (ProductID, SizeName) VALUES (?, ?)", product_id, trimmed_size)
                processed_size_for_response = trimmed_size

            await cursor.execute("""
                SELECT ProductID, ProductName, ProductTypeID, ProductCategory, ProductDescription, ProductPrice, ProductImage
                FROM Products WHERE ProductID = ? """, product_id)
            updated_product_row = await cursor.fetchone()
            if not updated_product_row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POS: Product not found after update attempt.")

            return PosProductOut(
                ProductID=updated_product_row.ProductID, ProductName=updated_product_row.ProductName,
                ProductTypeID=updated_product_row.ProductTypeID, ProductCategory=updated_product_row.ProductCategory,
                ProductDescription=updated_product_row.ProductDescription,
                ProductPrice=float(updated_product_row.ProductPrice or 0.0),
                ProductImage=_construct_full_url_for_pos_served_image(updated_product_row.ProductImage), # MODIFIED
                ProductSize=processed_size_for_response
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POS: Error in update_product_in_pos for ID {product_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="POS: Error updating product.")
    finally:
        if conn: await conn.close()

@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_from_pos(product_id: int, token: str = Depends(oauth2_scheme_from_is)):
    await validate_token_and_roles_is_caller(token, ["admin", "manager"])
    conn = None
    try:
        conn = await get_db_connection()
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT ProductImage FROM Products WHERE ProductID = ?", product_id) # Get image path
            product_row = await cursor.fetchone()
            if not product_row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"POS: Product with ID {product_id} not found for deletion.")
            
            pos_db_image_path_to_delete = product_row.ProductImage

            await cursor.execute("DELETE FROM Size WHERE ProductID = ?", product_id)
            await cursor.execute("DELETE FROM Products WHERE ProductID = ?", product_id)
            
            # MODIFIED: Delete the physical image file from POS server
            if pos_db_image_path_to_delete:
                # pos_db_image_path_to_delete is like "/pos_product_images/filename.jpg"
                filename_to_delete = Path(pos_db_image_path_to_delete).name
                physical_file_to_delete = POS_UPLOAD_DIRECTORY_PHYSICAL / filename_to_delete
                if physical_file_to_delete.exists():
                    try:
                        os.remove(physical_file_to_delete)
                        logger.info(f"POS: Deleted product image file: {physical_file_to_delete}")
                    except OSError as e:
                        logger.error(f"POS: Error deleting product image file {physical_file_to_delete}: {e}")
                        # Log error but don't fail the whole product deletion for this.
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POS: Error deleting product ID {product_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="POS: Error deleting product.")
    finally:
        if conn: await conn.close()


# --- POS Size Specific Endpoints --- (No changes here as they don't handle images directly)
# GET /Products/products/{product_id}/sizes
# POST /Products/products/{product_id}/sizes
# POST /Products/products/add-size-by-name
# (These remain the same as your original code)
@router.get("/products/{product_id}/sizes", response_model=List[PosProductSizeOut])
async def get_sizes_for_specific_product_pos(product_id: int, token: str = Depends(oauth2_scheme_direct_pos)):
    await validate_token_and_roles_direct_pos_caller(token, ["admin", "manager", "staff"])
    conn = None
    try:
        conn = await get_db_connection()
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT ProductID FROM Products WHERE ProductID = ?", product_id)
            if not await cursor.fetchone():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"POS: Product with ID {product_id} not found.")

            await cursor.execute("SELECT SizeID, ProductID, SizeName FROM Size WHERE ProductID = ? ORDER BY SizeName", product_id)
            return [PosProductSizeOut(SizeID=r.SizeID, ProductID=r.ProductID, SizeName=r.SizeName) for r in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"POS: Error getting sizes for product ID {product_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="POS: Error fetching product sizes.")
    finally:
        if conn: await conn.close()


@router.post("/products/{product_id}/sizes", response_model=PosProductSizeOut, status_code=status.HTTP_201_CREATED)
async def add_size_to_pos_product_by_id(
    product_id: int, size_payload: PosSizeCreate, token: str = Depends(oauth2_scheme_from_is)
):
    await validate_token_and_roles_is_caller(token, ["admin", "manager", "staff"])
    conn = None
    trimmed_size_name = size_payload.SizeName.strip()

    if not trimmed_size_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="POS: SizeName cannot be empty.")

    try:
        conn = await get_db_connection()
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT ProductName FROM Products WHERE ProductID = ?", product_id)
            if not await cursor.fetchone():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"POS: Product with ID {product_id} not found.")

            await cursor.execute(
                "SELECT SizeID FROM Size WHERE ProductID = ? AND SizeName COLLATE Latin1_General_CI_AS = ?",
                product_id, trimmed_size_name
            )
            if await cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"POS: Size '{trimmed_size_name}' already exists for product ID {product_id}."
                )

            await cursor.execute(
                "INSERT INTO Size (ProductID, SizeName) OUTPUT INSERTED.SizeID VALUES (?, ?)",
                product_id, trimmed_size_name
            )
            new_size_id_row = await cursor.fetchone()
            if not new_size_id_row or not new_size_id_row.SizeID:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="POS: Failed to add size or retrieve new SizeID.")

            return PosProductSizeOut(
                SizeID=new_size_id_row.SizeID, ProductID=product_id, SizeName=trimmed_size_name
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POS: Error adding size by ID to product {product_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="POS: An unexpected error occurred while adding the size by ID.")
    finally:
        if conn: await conn.close()

@router.post("/products/add-size-by-name", response_model=PosProductSizeOut, status_code=status.HTTP_201_CREATED)
async def add_size_to_pos_product_by_name(
    payload: PosAddSizeByProductNamePayload, token: str = Depends(oauth2_scheme_from_is)
):
    await validate_token_and_roles_is_caller(token, ["admin", "manager", "staff"])
    conn = None
    trimmed_product_name = payload.ProductName.strip()
    trimmed_size_name = payload.SizeName.strip()

    if not trimmed_product_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="POS: ProductName cannot be empty.")
    if not trimmed_size_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="POS: SizeName cannot be empty.")

    try:
        conn = await get_db_connection()
        async with conn.cursor() as cursor:
            await cursor.execute(
                "SELECT ProductID FROM Products WHERE ProductName COLLATE Latin1_General_CI_AS = ?",
                trimmed_product_name
            )
            product_row = await cursor.fetchone()
            if not product_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"POS: Product with name '{trimmed_product_name}' not found."
                )
            pos_product_id = product_row.ProductID

            await cursor.execute(
                "SELECT SizeID FROM Size WHERE ProductID = ? AND SizeName COLLATE Latin1_General_CI_AS = ?",
                pos_product_id, trimmed_size_name
            )
            if await cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"POS: Size '{trimmed_size_name}' already exists for product '{trimmed_product_name}' (ID: {pos_product_id})."
                )

            await cursor.execute(
                "INSERT INTO Size (ProductID, SizeName) OUTPUT INSERTED.SizeID VALUES (?, ?)",
                pos_product_id, trimmed_size_name
            )
            new_size_id_row = await cursor.fetchone()
            if not new_size_id_row or not new_size_id_row.SizeID:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="POS: Failed to add size or retrieve new SizeID.")

            return PosProductSizeOut(
                SizeID=new_size_id_row.SizeID,
                ProductID=pos_product_id,
                SizeName=trimmed_size_name
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POS: Error adding size by name to product '{trimmed_product_name}': {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="POS: An unexpected error occurred while adding the size by name.")
    finally:
        if conn: await conn.close()