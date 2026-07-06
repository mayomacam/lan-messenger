import pyotp
import os
import time
from db import Database
import audit

def test_mfa_logic():
    db_name = "test_mfa.db"
    key_file = ".test_mfa.key"
    if os.path.exists(db_name): os.remove(db_name)
    if os.path.exists(key_file): os.remove(key_file)

    password = "master_password"
    db = Database(password, db_name=db_name, key_file=key_file)
    audit.init_logger(db)

    # 1. Generate Secret
    secret = pyotp.random_base32()
    print(f"Generated Secret: {secret}")

    # 2. Store Secret (Encrypted)
    db.set_config("mfa_secret", secret, encrypt=True)
    db.set_config("mfa_enabled", "1")

    # 3. Verify Retrieval
    retrieved_secret = db.get_config("mfa_secret", decrypt=True)
    assert retrieved_secret == secret
    print("Secret storage and retrieval verified.")

    # 4. Verify TOTP Logic
    totp = pyotp.TOTP(secret)
    code = totp.now()
    print(f"Current TOTP code: {code}")

    assert totp.verify(code)
    print("TOTP verification verified.")

    # 5. Verify Invalid Code
    assert not totp.verify("000000")
    print("Invalid TOTP rejected as expected.")

    db.close()
    if os.path.exists(db_name): os.remove(db_name)
    if os.path.exists(key_file): os.remove(key_file)
    print("MFA Logic Test PASSED")

if __name__ == "__main__":
    test_mfa_logic()
