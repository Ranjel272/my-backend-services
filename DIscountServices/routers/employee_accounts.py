from fastapi import APIRouter, HTTPException, Depends, status, Form, UploadFile, File
from datetime import datetime, date
from database import get_db_connection
from routers.auth import get_current_active_user, role_required
import bcrypt
import shutil
import os
from typing import Optional

router = APIRouter()

# Configuration for image uploads
UPLOAD_DIRECTORY = "uploads"
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)

@router.post('/create', dependencies=[Depends(role_required(["admin"]))])
async def create_user(
    fullName: str = Form(...),
    username: str = Form(None),
    password: str = Form(...),
    userRole: str = Form(...),
    emailAddress: str = Form(...),
    phoneNumber: Optional[str] = Form(None),
    hireDate: Optional[date] = Form(None),
    uploadImage: Optional[UploadFile] = File(None),
):
    if userRole not in ['admin', 'manager', 'cashier']:
        raise HTTPException(status_code=400, detail="Invalid role")

    if not password.strip():
        raise HTTPException(status_code=400, detail="Password/Passcode is required")

    conn = None
    cursor = None
    try:
        conn = await get_db_connection()
        cursor = await conn.cursor()

        await cursor.execute("SELECT 1 FROM Users WHERE FullName = ? AND isDisabled = 0", (fullName,))
        if await cursor.fetchone():
            raise HTTPException(status_code=400, detail="Full name is already used")

        await cursor.execute("SELECT 1 FROM Users WHERE EmailAddress = ? AND isDisabled = 0", (emailAddress,))
        if await cursor.fetchone():
            raise HTTPException(status_code=400, detail="Email address is already used")

        db_username_to_store = None

        if userRole == 'cashier':
            if not (password.isdigit() and len(password) == 6):
                raise HTTPException(status_code=400, detail="Cashier passcode must be exactly 6 digits.")
            db_username_to_store = "cashier"
            await cursor.execute('''
                SELECT UserPassword FROM Users WHERE UserRole = 'cashier' AND isDisabled = 0
            ''')
            all_cashier_passwords = await cursor.fetchall()
            for row in all_cashier_passwords:
                if row[0] and bcrypt.checkpw(password.encode('utf-8'), row[0].encode('utf-8')):
                    raise HTTPException(status_code=400, detail="This passcode is already used by another cashier.")
        elif userRole in ['admin', 'manager']:
            if not username or not username.strip():
                raise HTTPException(status_code=400, detail="Username is required for admin/manager roles")
            if username.lower() == 'cashier':
                raise HTTPException(status_code=400, detail="'cashier' is a reserved username and cannot be used for admin/manager roles.")
            db_username_to_store = username
            await cursor.execute(
                "SELECT 1 FROM Users WHERE Username = ? AND UserRole IN ('admin', 'manager') AND isDisabled = 0",
                (db_username_to_store,)
            )
            if await cursor.fetchone():
                raise HTTPException(status_code=400, detail=f"Username '{db_username_to_store}' is already taken by an admin or manager.")
        else:
            raise HTTPException(status_code=400, detail="Invalid user role for username assignment.")

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        image_filename_to_store = None
        if uploadImage:
            image_filename_to_store = f"{datetime.now().timestamp()}_{uploadImage.filename}"
            file_path = os.path.join(UPLOAD_DIRECTORY, image_filename_to_store)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(uploadImage.file, buffer)

        await cursor.execute('''
            INSERT INTO Users (FullName, Username, UserPassword, UserRole, CreatedAt, isDisabled, EmailAddress, UploadImage, PhoneNumber, HireDate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (fullName, db_username_to_store, hashed_password, userRole, datetime.utcnow(), 0, emailAddress, image_filename_to_store, phoneNumber, hireDate))
        await conn.commit()

    except HTTPException:
        raise
    except Exception as e:
        if uploadImage and 'image_filename_to_store' in locals() and image_filename_to_store and os.path.exists(os.path.join(UPLOAD_DIRECTORY, image_filename_to_store)):
            os.remove(os.path.join(UPLOAD_DIRECTORY, image_filename_to_store))
        print(f"Error in create_user: {e}")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred during user creation.")
    finally:
        if cursor: await cursor.close()
        if conn: await conn.close()
    return {'message': f'{userRole.capitalize()} created successfully!'}

@router.get('/list-employee-accounts', dependencies=[Depends(role_required(['admin']))])
async def list_users():
    conn = None
    cursor = None
    try:
        conn = await get_db_connection()
        cursor = await conn.cursor()
        await cursor.execute('''
            SELECT UserID, FullName, Username, UserRole, CreatedAt, EmailAddress, UploadImage, PhoneNumber, HireDate
            FROM Users
            WHERE isDisabled = 0
        ''')
        users_db = await cursor.fetchall()
    except Exception as e:
        print(f"Error in list_users: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve user list.")
    finally:
        if cursor: await cursor.close()
        if conn: await conn.close()

    users_list = []
    for u in users_db:
        users_list.append({
            "userID": u[0], "fullName": u[1], "username": u[2], "userRole": u[3],
            "createdAt": u[4].isoformat() if u[4] else None,
            "emailAddress": u[5], "uploadImage": u[6], "phoneNumber": u[7],
            "hireDate": u[8].isoformat() if u[8] else None,
        })
    return users_list

@router.put("/update/{user_id}", dependencies=[Depends(role_required(['admin']))])
async def update_user(
    user_id: int,
    fullName: Optional[str] = Form(None),
    username: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    userRole: Optional[str] = Form(None),
    emailAddress: Optional[str] = Form(None),
    phoneNumber: Optional[str] = Form(None),
    hireDate: Optional[date] = Form(None),
    uploadImage: Optional[UploadFile] = File(None),
):
    conn = None
    cursor = None
    try:
        conn = await get_db_connection()
        cursor = await conn.cursor()

        # Fetch current user details including role and username
        await cursor.execute("SELECT UploadImage, UserRole, Username, UserPassword FROM Users WHERE UserID = ? AND isDisabled = 0", (user_id,))
        current_user_db_info = await cursor.fetchone()
        if not current_user_db_info:
            raise HTTPException(status_code=404, detail="User not found")

        current_image_filename = current_user_db_info[0]
        current_user_role_db = current_user_db_info[1]
        current_username_db = current_user_db_info[2]
        # current_password_hash_db = current_user_db_info[3] # Not directly used for comparison, but for context

        updates = []
        values = []

        if fullName:
            # Optional: Check for FullName collision if it's being changed
            # await cursor.execute("SELECT 1 FROM Users WHERE FullName = ? AND UserID != ? AND isDisabled = 0", (fullName, user_id))
            # if await cursor.fetchone():
            #     raise HTTPException(status_code=400, detail="Full name is already used by another user")
            updates.append('FullName = ?')
            values.append(fullName)

        if emailAddress:
            await cursor.execute("SELECT 1 FROM Users WHERE EmailAddress = ? AND UserID != ? AND isDisabled = 0", (emailAddress, user_id))
            if await cursor.fetchone():
                raise HTTPException(status_code=400, detail="Email address is already used by another user")
            updates.append('EmailAddress = ?')
            values.append(emailAddress)

        # --- Role and Username Change Logic ---
        effective_role = current_user_role_db # Start with current role
        if userRole and userRole != current_user_role_db: # If role is being changed
            if userRole not in ['admin', 'manager', 'cashier']:
                raise HTTPException(status_code=400, detail="Invalid new role specified.")
            updates.append('UserRole = ?')
            values.append(userRole)
            effective_role = userRole # New role becomes the effective role for subsequent checks

            if userRole == 'cashier':
                # Username for cashier must be 'cashier'
                if current_username_db != 'cashier': # Only update if not already 'cashier' (though it should be if role was cashier)
                    updates.append('Username = ?')
                    values.append('cashier')
                # Password (passcode) for cashier (if role changes TO cashier)
                if not password:
                    raise HTTPException(status_code=400, detail="A 6-digit passcode is required when changing role to Cashier.")
                # Further password validation for cashier happens in password section

            elif userRole in ['admin', 'manager']:
                if not username or not username.strip():
                    raise HTTPException(status_code=400, detail=f"Username is required when changing role to {userRole}.")
                if username.lower() == 'cashier':
                     raise HTTPException(status_code=400, detail="'cashier' is a reserved username.")
                # Check for username collision
                await cursor.execute(
                    "SELECT 1 FROM Users WHERE Username = ? AND UserID != ? AND UserRole IN ('admin', 'manager') AND isDisabled = 0",
                    (username, user_id)
                )
                if await cursor.fetchone():
                    raise HTTPException(status_code=400, detail=f"Username '{username}' is already taken by another admin or manager.")
                updates.append('Username = ?')
                values.append(username)
                # If changing from Cashier to Admin/Manager, a new password is required
                if current_user_role_db == 'cashier' and not password:
                    raise HTTPException(status_code=400, detail="A new password is required when changing role from Cashier to Admin/Manager.")

        elif username and username != current_username_db and current_user_role_db in ['admin', 'manager']:
            # Role is NOT changing, but admin/manager username IS changing
            if not username.strip():
                raise HTTPException(status_code=400, detail="Username cannot be empty for admin/manager.")
            if username.lower() == 'cashier':
                raise HTTPException(status_code=400, detail="'cashier' username is reserved.")
            await cursor.execute(
                "SELECT 1 FROM Users WHERE Username = ? AND UserID != ? AND UserRole IN ('admin', 'manager') AND isDisabled = 0",
                (username, user_id)
            )
            if await cursor.fetchone():
                raise HTTPException(status_code=400, detail=f"Username '{username}' is already taken by another admin or manager.")
            updates.append('Username = ?')
            values.append(username)

        # --- Password Update Logic ---
        if password and password.strip(): # If a new password is provided
            if effective_role == 'cashier':
                if not (password.isdigit() and len(password) == 6):
                    raise HTTPException(status_code=400, detail="Passcode for Cashier must be exactly 6 digits.")
                # Check for passcode collision with OTHER cashiers
                await cursor.execute('''
                    SELECT UserPassword FROM Users WHERE UserRole = 'cashier' AND UserID != ? AND isDisabled = 0
                ''', (user_id,))
                all_other_cashier_passwords = await cursor.fetchall()
                for row in all_other_cashier_passwords:
                    if row[0] and bcrypt.checkpw(password.encode('utf-8'), row[0].encode('utf-8')):
                        raise HTTPException(status_code=400, detail="This passcode is already used by another cashier.")
            # No specific format validation for admin/manager password beyond being non-empty

            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            updates.append('UserPassword = ?')
            values.append(hashed_password)


        if phoneNumber is not None: # Allow empty string to clear phone number
            updates.append('PhoneNumber = ?')
            values.append(phoneNumber if phoneNumber.strip() else None) # Store NULL if empty
        if hireDate:
            updates.append('HireDate = ?')
            values.append(hireDate)

        new_image_filename_to_store = None
        if uploadImage:
            new_image_filename_to_store = f"{datetime.now().timestamp()}_{uploadImage.filename}"
            file_path = os.path.join(UPLOAD_DIRECTORY, new_image_filename_to_store)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(uploadImage.file, buffer)
            updates.append('UploadImage = ?')
            values.append(new_image_filename_to_store)

        if not updates and not new_image_filename_to_store : # Check if any actual update fields were provided
             return {'message': 'No fields to update'}


        values.append(user_id) # Add user_id for the WHERE clause
        query = f"UPDATE Users SET {', '.join(updates)} WHERE UserID = ? AND isDisabled = 0"
        await cursor.execute(query, tuple(values))
        await conn.commit()

        # Fixed line: removed the await from cursor.rowcount
        if cursor.rowcount == 0:
            # This might happen if user_id was valid but isDisabled became 1 concurrently, or no actual changes made that DB recognized
            # For robust check, ensure updates list was not empty before commit, or re-fetch to confirm
            # For now, we assume commit was successful if no error
            pass


        # Clean up old image if new one was uploaded and an old one existed
        if new_image_filename_to_store and current_image_filename:
            old_image_path = os.path.join(UPLOAD_DIRECTORY, current_image_filename)
            if os.path.exists(old_image_path):
                try:
                    os.remove(old_image_path)
                except Exception as e:
                    print(f"Error deleting old image {old_image_path}: {e}") # Log error but don't fail request

    except HTTPException:
        raise
    except Exception as e:
        # Clean up newly uploaded image if error occurred during DB operation
        if uploadImage and 'new_image_filename_to_store' in locals() and new_image_filename_to_store and os.path.exists(os.path.join(UPLOAD_DIRECTORY, new_image_filename_to_store)):
            try:
                os.remove(os.path.join(UPLOAD_DIRECTORY, new_image_filename_to_store))
            except Exception as del_e:
                print(f"Error cleaning up uploaded image on failure: {del_e}")
        print(f"Error in update_user: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An internal server error occurred during user update: {str(e)}")
    finally:
        if cursor: await cursor.close()
        if conn: await conn.close()

    return {'message': 'User updated successfully'}


@router.delete('/delete/{user_id}', dependencies=[Depends(role_required(['admin']))])
async def delete_user(
    user_id: int,
):
    conn = None
    cursor = None
    try:
        conn = await get_db_connection()
        cursor = await conn.cursor()
        await cursor.execute("SELECT 1 FROM Users WHERE UserID = ? AND isDisabled = 0", (user_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="User not found or already disabled.")
        await cursor.execute("UPDATE Users SET isDisabled = 1 WHERE UserID = ? ", (user_id,))
        await conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in delete_user: {e}")
        raise HTTPException(status_code=500, detail="An internal server error occurred during user deletion.")
    finally:
        if cursor: await cursor.close()
        if conn: await conn.close()

    return {'message': 'User soft deleted successfully'}