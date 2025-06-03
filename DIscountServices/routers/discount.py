# routers/discount.py

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field # Field is used in models
from typing import List, Optional
import httpx
from decimal import Decimal
from datetime import datetime

# --- Database Connection Import ---
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from database import get_db_connection
except ImportError:
    print("ERROR: Could not import get_db_connection from database.py.")
    async def get_db_connection():
        raise NotImplementedError("Database connection not configured.")


# --- Scheme and Validation specifically for services on Auth port 9000 ---
oauth2_scheme_port9000 = OAuth2PasswordBearer(
    tokenUrl="http://localhost:9000/auth/token",
    scheme_name="OAuth2PasswordBearerPort9000"
)

async def validate_token_and_roles_port9000(
    token: str,
    allowed_roles: Optional[List[str]] = None
):
    auth_url = "http://localhost:9000/auth/users/me"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(auth_url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            error_detail = f"Auth service (9000) error: {e.response.text}"
            try:
                auth_error_json = e.response.json()
                if "detail" in auth_error_json:
                    error_detail = f"Auth service (9000) error: {auth_error_json['detail']}"
            except Exception:
                pass
            raise HTTPException(status_code=e.response.status_code, detail=error_detail)
        except httpx.RequestError as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Could not connect to auth service (9000): {str(e)}")

    user_data = response.json()
    user_role = user_data.get("userRole") 

    if allowed_roles:
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied (9000). User does not have the required role."
            )
    return user_data # Contains 'user_id', 'sub' (username), 'userRole' etc.

# --- Router for Discount Services ---
router_discounts = APIRouter(
    prefix="/discounts",
    tags=["discounts"]
)

# --- Models for Discounts ---
class DiscountBase(BaseModel):
    DiscountName: str
    ProductName: str 
    PercentageValue: float = Field(gt=0, lt=100, description="Percentage value, e.g., 10.5 for 10.5% (0 < value < 100)")
    MinimumSpend: Optional[float] = Field(None, ge=0, description="Minimum spend required to apply discount, if any.")
    ValidFrom: datetime
    ValidTo: datetime
    # MODIFIED: Expect Username in payload instead of UserID
    Username: str = Field(..., description="The username of the user associated with this discount action.")
    Status: str = Field(..., min_length=1, description="Status of the discount (e.g., 'active', 'inactive', 'expired')")

class DiscountCreate(DiscountBase):
    pass

class DiscountUpdate(DiscountBase): # For PUT, all fields from Base are expected
    pass

# Output models still include ProductID and ProductName (fetched/resolved) and UserID
class DiscountOut(BaseModel): 
    DiscountID: int
    DiscountName: str
    ProductID: int
    ProductName: str 
    PercentageValue: float
    MinimumSpend: Optional[float]
    ValidFrom: datetime
    ValidTo: datetime
    UserID: int # UserID is stored in DB and returned
    Status: str
    CreatedAt: datetime

class DiscountGet(DiscountOut): 
    pass


# --- Helper function to get UserID from Username ---
async def get_user_id_from_username(username: str, db_conn) -> int:
    """
    Fetches UserID from the Users table based on Username.
    Assumes 'Users' table with 'UserID' and 'Username' columns.
    Adjust table/column names if different.
    """
    async with db_conn.cursor() as cursor:
        # Using COLLATE for case-insensitive username lookup, adjust if needed
        await cursor.execute(
            "SELECT UserID FROM Users WHERE Username COLLATE Latin1_General_CI_AS = ?", 
            username
        )
        user_record = await cursor.fetchone()
        if not user_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with username '{username}' not found in the system."
            )
        return user_record.UserID

# --- Discount Endpoints ---
def get_current_user_with_roles(allowed_roles: List[str]):
    async def _get_current_user(
        user_data: dict = Depends(
            lambda token_param=Depends(oauth2_scheme_port9000):
                validate_token_and_roles_port9000(token=token_param, allowed_roles=allowed_roles)
        )
    ):
        return user_data
    return _get_current_user

@router_discounts.post("/", response_model=DiscountOut, status_code=status.HTTP_201_CREATED)
async def create_discount(
    discount_data: DiscountCreate,
    # current_user_from_token: dict = Depends(get_current_user_with_roles(["admin", "manager"])) # For authorization
    # The above can be used if you need to check the role of the person making the request
    # but the UserID for the discount will come from discount_data.Username
    current_user_from_token: dict = Depends(get_current_user_with_roles(["admin", "manager"]))

):
    conn = None
    try:
        conn = await get_db_connection()

        # 1. Get UserID based on the Username provided in the payload
        user_id_for_discount = await get_user_id_from_username(discount_data.Username, conn)

        async with conn.cursor() as cursor:
            # 2. Find ProductID based on discount_data.ProductName (case-insensitive search)
            await cursor.execute(
                "SELECT ProductID, ProductName FROM Products WHERE ProductName COLLATE Latin1_General_CI_AS = ?",
                discount_data.ProductName
            )
            product_row = await cursor.fetchone()
            if not product_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Product with name '{discount_data.ProductName}' not found."
                )
            found_product_id = product_row.ProductID
            actual_product_name = product_row.ProductName

            # 3. Check for duplicate DiscountName (case-insensitive for SQL Server)
            await cursor.execute(
                "SELECT 1 FROM Discounts WHERE DiscountName COLLATE Latin1_General_CI_AS = ?",
                discount_data.DiscountName
            )
            if await cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Discount name '{discount_data.DiscountName}' already exists."
                )

            # 4. Validate dates: ValidFrom must be before ValidTo
            if discount_data.ValidFrom >= discount_data.ValidTo:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ValidFrom date must be before ValidTo date."
                )

            # 5. Insert the new discount using found_product_id and resolved user_id_for_discount
            sql = """
                INSERT INTO Discounts (
                    DiscountName, ProductID, PercentageValue, MinimumSpend,
                    ValidFrom, ValidTo, UserID, Status, CreatedAt
                )
                OUTPUT INSERTED.DiscountID, INSERTED.DiscountName, INSERTED.ProductID,
                       INSERTED.PercentageValue, INSERTED.MinimumSpend, INSERTED.ValidFrom,
                       INSERTED.ValidTo, INSERTED.UserID, INSERTED.Status, INSERTED.CreatedAt
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, GETUTCDATE())
            """
            await cursor.execute(
                sql,
                discount_data.DiscountName,
                found_product_id, 
                Decimal(str(discount_data.PercentageValue)),
                Decimal(str(discount_data.MinimumSpend)) if discount_data.MinimumSpend is not None else None,
                discount_data.ValidFrom,
                discount_data.ValidTo,
                user_id_for_discount, # Use the UserID resolved from the payload's Username
                discount_data.Status
            )
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create discount after insert attempt."
                )
            await conn.commit()

            return DiscountOut(
                DiscountID=row.DiscountID,
                DiscountName=row.DiscountName,
                ProductID=row.ProductID, 
                ProductName=actual_product_name, 
                PercentageValue=float(row.PercentageValue),
                MinimumSpend=float(row.MinimumSpend) if row.MinimumSpend is not None else None,
                ValidFrom=row.ValidFrom,
                ValidTo=row.ValidTo,
                UserID=row.UserID, # This will be the user_id_for_discount
                Status=row.Status,
                CreatedAt=row.CreatedAt
            )
    except HTTPException:
        raise
    except Exception as e:
        if conn: await conn.rollback()
        error_message = f"An unexpected error occurred: {str(e)}"
        print(f"ERROR in create_discount: {error_message}") 
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_message)
    finally:
        if conn:
            await conn.close()

@router_discounts.get("/", response_model=List[DiscountGet])
async def get_all_discounts(
    current_user: dict = Depends(get_current_user_with_roles(["admin", "manager", "staff"])) # For authorization
):
    conn = None
    try:
        conn = await get_db_connection()
        async with conn.cursor() as cursor:
            await cursor.execute("""
                SELECT
                    d.DiscountID, d.DiscountName, d.ProductID, p.ProductName,
                    d.PercentageValue, d.MinimumSpend, d.ValidFrom, d.ValidTo,
                    d.UserID, d.Status, d.CreatedAt
                FROM Discounts d
                LEFT JOIN Products p ON d.ProductID = p.ProductID
                ORDER BY d.DiscountID DESC
            """)
            rows = await cursor.fetchall()
            return [
                DiscountGet(
                    DiscountID=row.DiscountID, DiscountName=row.DiscountName,
                    ProductID=row.ProductID, ProductName=row.ProductName, 
                    PercentageValue=float(row.PercentageValue),
                    MinimumSpend=float(row.MinimumSpend) if row.MinimumSpend is not None else None,
                    ValidFrom=row.ValidFrom, ValidTo=row.ValidTo,
                    UserID=row.UserID, Status=row.Status, CreatedAt=row.CreatedAt
                ) for row in rows
            ]
    except Exception as e:
        error_message = f"An unexpected error occurred while fetching all discounts: {str(e)}"
        print(f"ERROR in get_all_discounts: {error_message}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_message)
    finally:
        if conn:
            await conn.close()

@router_discounts.get("/{discount_id}", response_model=DiscountGet)
async def get_discount_by_id(
    discount_id: int,
    current_user: dict = Depends(get_current_user_with_roles(["admin", "manager", "staff"])) # For authorization
):
    conn = None
    try:
        conn = await get_db_connection()
        async with conn.cursor() as cursor:
            await cursor.execute("""
                SELECT
                    d.DiscountID, d.DiscountName, d.ProductID, p.ProductName,
                    d.PercentageValue, d.MinimumSpend, d.ValidFrom, d.ValidTo,
                    d.UserID, d.Status, d.CreatedAt
                FROM Discounts d
                LEFT JOIN Products p ON d.ProductID = p.ProductID
                WHERE d.DiscountID = ?
            """, discount_id)
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Discount ID {discount_id} not found.")
            return DiscountGet(
                DiscountID=row.DiscountID, DiscountName=row.DiscountName,
                ProductID=row.ProductID, ProductName=row.ProductName, 
                PercentageValue=float(row.PercentageValue),
                MinimumSpend=float(row.MinimumSpend) if row.MinimumSpend is not None else None,
                ValidFrom=row.ValidFrom, ValidTo=row.ValidTo,
                UserID=row.UserID, Status=row.Status, CreatedAt=row.CreatedAt
            )
    except HTTPException:
        raise
    except Exception as e:
        error_message = f"An unexpected error occurred while fetching discount by ID: {str(e)}"
        print(f"ERROR in get_discount_by_id: {error_message}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_message)
    finally:
        if conn:
            await conn.close()

@router_discounts.put("/{discount_id}", response_model=DiscountOut)
async def update_discount(
    discount_id: int,
    discount_data: DiscountUpdate,
    current_user_from_token: dict = Depends(get_current_user_with_roles(["admin", "manager"])) # For authorization
):
    conn = None
    try:
        conn = await get_db_connection()

        # 1. Get UserID based on the Username provided in the payload
        user_id_for_discount = await get_user_id_from_username(discount_data.Username, conn)

        async with conn.cursor() as cursor:
            # 2. Check if discount exists
            await cursor.execute("SELECT 1 FROM Discounts WHERE DiscountID = ?", discount_id)
            if not await cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Discount ID {discount_id} not found for update."
                )

            # 3. Find ProductID based on discount_data.ProductName (case-insensitive)
            await cursor.execute(
                "SELECT ProductID, ProductName FROM Products WHERE ProductName COLLATE Latin1_General_CI_AS = ?",
                discount_data.ProductName
            )
            product_row = await cursor.fetchone()
            if not product_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Product with name '{discount_data.ProductName}' not found for update."
                )
            found_product_id = product_row.ProductID
            # actual_product_name = product_row.ProductName # Not strictly needed for update unless re-fetching

            # 4. Check for duplicate DiscountName (case-insensitive) for another discount
            await cursor.execute(
                "SELECT 1 FROM Discounts WHERE DiscountName COLLATE Latin1_General_CI_AS = ? AND DiscountID != ?",
                discount_data.DiscountName, discount_id
            )
            if await cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Discount name '{discount_data.DiscountName}' already exists for another discount."
                )

            # 5. Validate dates
            if discount_data.ValidFrom >= discount_data.ValidTo:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ValidFrom date must be before ValidTo date."
                )

            # 6. Update the discount using found_product_id and resolved user_id_for_discount
            sql = """
                UPDATE Discounts SET
                    DiscountName = ?, ProductID = ?, PercentageValue = ?, MinimumSpend = ?,
                    ValidFrom = ?, ValidTo = ?, UserID = ?, Status = ?
                WHERE DiscountID = ?
            """
            await cursor.execute(
                sql,
                discount_data.DiscountName,
                found_product_id, 
                Decimal(str(discount_data.PercentageValue)),
                Decimal(str(discount_data.MinimumSpend)) if discount_data.MinimumSpend is not None else None,
                discount_data.ValidFrom,
                discount_data.ValidTo,
                user_id_for_discount, # Use the UserID resolved from the payload's Username
                discount_data.Status,
                discount_id
            )

            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, 
                    detail="Discount not updated. It might have been deleted concurrently or data was identical."
                )
            await conn.commit()

            # Fetch the updated discount to return it
            await cursor.execute("""
                SELECT d.DiscountID, d.DiscountName, d.ProductID, p.ProductName,
                       d.PercentageValue, d.MinimumSpend, d.ValidFrom, d.ValidTo,
                       d.UserID, d.Status, d.CreatedAt
                FROM Discounts d
                LEFT JOIN Products p ON d.ProductID = p.ProductID
                WHERE d.DiscountID = ?
            """, discount_id)
            row = await cursor.fetchone()
            if not row: 
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Updated discount not found after update attempt.")

            return DiscountOut(
                DiscountID=row.DiscountID,
                DiscountName=row.DiscountName,
                ProductID=row.ProductID,
                ProductName=row.ProductName, 
                PercentageValue=float(row.PercentageValue),
                MinimumSpend=float(row.MinimumSpend) if row.MinimumSpend is not None else None,
                ValidFrom=row.ValidFrom,
                ValidTo=row.ValidTo,
                UserID=row.UserID, # This will be the user_id_for_discount
                Status=row.Status,
                CreatedAt=row.CreatedAt
            )
    except HTTPException:
        raise
    except Exception as e:
        if conn: await conn.rollback()
        error_message = f"An unexpected error occurred during update: {str(e)}"
        print(f"ERROR in update_discount: {error_message}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_message)
    finally:
        if conn:
            await conn.close()

@router_discounts.delete("/{discount_id}", status_code=status.HTTP_200_OK)
async def delete_discount(
    discount_id: int,
    current_user: dict = Depends(get_current_user_with_roles(["admin", "manager"])) # For authorization
    # If you need to log who deleted it based on a Username in the payload (not typical for DELETE):
    # username_payload: Optional[UsernamePayload] = None 
    # ... then resolve username_payload.Username to UserID if needed for auditing.
):
    conn = None
    try:
        conn = await get_db_connection()
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT 1 FROM Discounts WHERE DiscountID = ?", discount_id)
            if not await cursor.fetchone():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Discount ID {discount_id} not found.")

            await cursor.execute("DELETE FROM Discounts WHERE DiscountID = ?", discount_id)
            if cursor.rowcount == 0:
                 raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discount could not be deleted (possibly already removed).")
            await conn.commit()
            return {"message": f"Discount ID {discount_id} deleted successfully."} 
    except HTTPException:
        raise
    except Exception as e:
        if conn: await conn.rollback()
        error_message = f"An unexpected error occurred during deletion: {str(e)}"
        print(f"ERROR in delete_discount: {error_message}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_message)
    finally:
        if conn:
            await conn.close()