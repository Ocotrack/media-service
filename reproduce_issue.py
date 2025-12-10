from fastapi import HTTPException
from typing import Optional
from dataclasses import dataclass

@dataclass
class MockMediaItem:
    id: str
    client_id: str
    user_id: Optional[str]
    path: str
    status: str = "ready"

# Copy of logic from app/main.py
def check_auth(item, client_id, user_id):
    # Logic from main.py
    if item.client_id != client_id:
        raise HTTPException(status_code=403, detail="Unauthorized for this path (client mismatch)")
    
    # Updated logic: Allow if item.user_id is None (System intent)
    # Only block if item HAS a user_id and it doesn't match the request user_id
    if item.user_id and user_id and item.user_id != user_id:
        raise HTTPException(status_code=403, detail=f"Unauthorized for this path. Item User: {item.user_id}, Request User: {user_id}")

    return "OK"

def run_tests():
    print("--- Reproduction Test ---")
    
    # Case 1: Item has NO user (None), Request has User 37
    # This simulates a public/system file accessed by a specific user.
    item_none = MockMediaItem(id="1", client_id="meximova", user_id=None, path="path/to/file")
    print("\n[Case 1] Item User=None, Request User='37'")
    try:
        check_auth(item_none, "meximova", "37")
        print("RESULT: ALLOWED (Verification failed - Expected Failure if bug exists, or maybe logic is actually fine?)")
    except HTTPException as e:
        print(f"RESULT: DENIED - {e.detail}")

    # Case 2: Item has User 'admin', Request has User 37
    item_admin = MockMediaItem(id="2", client_id="meximova", user_id="admin", path="path/to/file")
    print("\n[Case 2] Item User='admin', Request User='37'")
    try:
        check_auth(item_admin, "meximova", "37")
        print("RESULT: ALLOWED")
    except HTTPException as e:
        print(f"RESULT: DENIED - {e.detail}")

    # Case 3: Item has User '37', Request has User '37'
    item_user = MockMediaItem(id="3", client_id="meximova", user_id="37", path="path/to/file")
    print("\n[Case 3] Item User='37', Request User='37'")
    try:
        check_auth(item_user, "meximova", "37")
        print("RESULT: ALLOWED")
    except HTTPException as e:
        print(f"RESULT: DENIED - {e.detail}")

if __name__ == "__main__":
    run_tests()
