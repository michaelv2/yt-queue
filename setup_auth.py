#!/usr/bin/env python
"""Setup authentication for yt-queue.

Usage:
    python setup_auth.py      # Interactive mode
    python setup_auth.py --password mypassword   # Non-interactive
"""

import sys
import argparse
from pathlib import Path
import bcrypt


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()


def main():
    parser = argparse.ArgumentParser(description="Setup password authentication for yt-queue")
    parser.add_argument("--password", help="Password to hash (if not provided, will prompt)")
    args = parser.parse_args()

    # Get password
    if args.password:
        password = args.password
    else:
        import getpass
        password = getpass.getpass("Enter password: ")
        if not password:
            print("Error: Password cannot be empty", file=sys.stderr)
            sys.exit(1)

        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Error: Passwords do not match", file=sys.stderr)
            sys.exit(1)

    # Hash the password
    password_hash = hash_password(password)

    # Print instructions
    print("\n" + "=" * 70)
    print("Authentication Setup Complete")
    print("=" * 70)
    print("\nTo enable authentication, set these environment variables:\n")
    print(f"export YTQUEUE_AUTH_ENABLED=true")
    print(f"export YTQUEUE_PASSWORD_HASH='{password_hash}'\n")
    print("Or add to your .env file:")
    print(f"YTQUEUE_AUTH_ENABLED=true")
    print(f"YTQUEUE_PASSWORD_HASH={password_hash}\n")
    print("Then restart the server:")
    print("uvicorn app.main:app --reload\n")

    # Also save to .env file if it exists
    env_file = Path(".env")
    if env_file.exists():
        print(f"Save to {env_file}? (y/n): ", end="")
        if input().lower() == "y":
            content = env_file.read_text()
            # Update or add the lines
            lines = content.split("\n")
            new_lines = []
            found_auth_enabled = False
            found_password_hash = False

            for line in lines:
                if line.startswith("YTQUEUE_AUTH_ENABLED="):
                    new_lines.append("YTQUEUE_AUTH_ENABLED=true")
                    found_auth_enabled = True
                elif line.startswith("YTQUEUE_PASSWORD_HASH="):
                    new_lines.append(f"YTQUEUE_PASSWORD_HASH={password_hash}")
                    found_password_hash = True
                else:
                    new_lines.append(line)

            if not found_auth_enabled:
                new_lines.append("YTQUEUE_AUTH_ENABLED=true")
            if not found_password_hash:
                new_lines.append(f"YTQUEUE_PASSWORD_HASH={password_hash}")

            env_file.write_text("\n".join(new_lines))
            print(f"✓ Updated {env_file}")


if __name__ == "__main__":
    main()
