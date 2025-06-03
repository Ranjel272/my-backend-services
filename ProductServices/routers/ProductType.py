# port 9001 (e.g., in a file like routers/product_type_pos_router.py)
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import httpx
from pydantic import BaseModel
from database import get_db_connection # Assuming you have this for service 9001's DB

# IMPORTANT: Align tokenUrl with the auth service that issues the tokens (e.g., from port 8000 context)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="http://localhost:8000/auth/token")

router = APIRouter()

# --- Pydantic Model for Port 9001 ---
class ProductTypeCreateRequest(BaseModel):
    productTypeName: str
    SizeRequired: int # <<<< ADDED this field

@router.post("/create")
async def create_product_type(
    request: ProductTypeCreateRequest,  # Model updated to include SizeRequired
    token: str = Depends(oauth2_scheme)  
):
    print(f"Service 9001 received token (first 10 chars): {token[:10]}...")
    # This will now print the payload including SizeRequired
    print(f"Service 9001 received request payload: {request.model_dump_json()}") 

    # --- Token Validation (same as before) ---
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "http://localhost:8000/auth/users/me",  # Validating against the auth server
            headers={"Authorization": f"Bearer {token}"}
        )

    print(f"Service 9001 Auth Service Response Status: {response.status_code}")
    if response.status_code != 200:
        print(f"Service 9001 Auth Service Response Body: {response.text}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token (checked by 9001)")

    user_data = response.json()
    print(f"Service 9001 Auth User Data: {user_data}")

    if user_data.get('userRole') != 'admin': # Or whatever role is needed for this action
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied (user role insufficient, checked by 9001)")

    # --- Database Operations for Service 9001 ---
    conn = await get_db_connection() # Connection to 9001's database
    cursor = await conn.cursor()
    new_pos_product_type_id = None

    try:
        # Check if product type already exists in 9001's DB (by name)
        await cursor.execute(
            "SELECT 1 FROM ProductType WHERE productTypeName COLLATE Latin1_General_CI_AS = ?", 
            (request.productTypeName,)
        )
        if await cursor.fetchone():
            raise HTTPException(status_code=400, detail=f"Product type '{request.productTypeName}' already exists in secondary service (9001)")

        # Insert into 9001's DB, now including SizeRequired
        # Assuming 'productTypeID' is an identity column in 9001's ProductType table as well
        # If not, remove "OUTPUT INSERTED.productTypeID" and the subsequent fetchone() for the ID.
        sql_insert_9001 = """
        INSERT INTO ProductType (productTypeName, SizeRequired)
        OUTPUT INSERTED.productTypeID 
        VALUES (?, ?);
        """
        await cursor.execute(
            sql_insert_9001, 
            (request.productTypeName, request.SizeRequired) # <<<< ADDED request.SizeRequired
        )
        
        id_row = await cursor.fetchone() # This line is for getting the ID of the newly inserted row
        if id_row and id_row[0] is not None:
            new_pos_product_type_id = int(id_row[0])
        else:
            # If your ProductType table in 9001 does NOT have an identity ID,
            # or you don't need to retrieve it, you can remove the id_row check and new_pos_product_type_id.
            # In that case, the INSERT query should not have the OUTPUT clause.
            await conn.rollback()
            print(f"Service 9001: Failed to retrieve ID after insert using OUTPUT. id_row: {id_row}")
            raise HTTPException(status_code=500, detail="Failed to retrieve ID after insert in secondary service (9001). Check ProductType table definition if ID retrieval is expected.")


        await conn.commit()
        print(f"Product type '{request.productTypeName}' (ID: {new_pos_product_type_id}, SizeRequired: {request.SizeRequired}) created successfully in secondary service (9001)")
    
    except HTTPException as http_exc: 
        # If the error is from the duplicate check, no rollback is needed yet.
        # If it's from the "Failed to retrieve ID" HTTPException, rollback was already called.
        raise http_exc
    except Exception as e:
        try:
            await conn.rollback() # Rollback for any other DML-related errors before commit
        except Exception as rb_exc:
            print(f"Service 9001: Rollback failed during general exception: {rb_exc}")
        print(f"Error saving to secondary service (9001) DB: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save to secondary DB (9001): {str(e)}")
    finally:
        if cursor:
            await cursor.close()
        if conn:
            await conn.close()

    return {"message": "Product type created successfully in secondary service (9001)"}
