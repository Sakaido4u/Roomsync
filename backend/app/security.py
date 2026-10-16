"""Password hashing.

Passwords are never stored as typed. bcrypt turns them into a one-way
hash; to check a login we hash what was typed and compare. Login tokens
and role checks will be added here in the login step.
"""

import bcrypt

# bcrypt only looks at the first 72 bytes of a password, so we refuse
# longer ones instead of silently ignoring the end.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    data = password.encode("utf-8")
    if len(data) > MAX_PASSWORD_BYTES:
        raise ValueError("Password is too long (maximum 72 bytes).")
    return bcrypt.hashpw(data, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    data = password.encode("utf-8")
    if len(data) > MAX_PASSWORD_BYTES:
        return False
    return bcrypt.checkpw(data, password_hash.encode("utf-8"))
