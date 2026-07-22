"""
One-time: mint a Google OAuth refresh token and store it (+ the client) in Secret Manager.

Remote-safe: uses a manual loopback paste instead of a local browser redirect, so it works on a
headless/cloud workstation. The refresh token is written straight to Secret Manager and NEVER
printed. Run interactively in your terminal:

  cd chinese-convo-live
  source bench/.venv/bin/activate && pip install -q google-auth-oauthlib
  PROJECT_ID=your-gcp-project OWNER_EMAIL=you@example.com \
    python local/mint_google_token.py /path/to/client_secret.json
"""
import json
import os
import subprocess
import sys

# Must be set BEFORE importing oauthlib: allow the http://localhost loopback redirect, and
# tolerate Google returning the scopes in a different order than requested.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google_auth_oauthlib.flow import InstalledAppFlow

PROJECT = os.getenv("PROJECT_ID", "your-gcp-project")
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "you@example.com")
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly",
          "https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/drive.readonly"]


def put_secret(name, value):
    """Create the secret (user-managed replication in us-east4 — the org's gcp.resourceLocations
    policy blocks 'global'/automatic), or add a new version if it already exists."""
    created = subprocess.run(
        ["gcloud", "secrets", "create", name, "--project", PROJECT,
         "--replication-policy", "user-managed", "--locations", "us-east4", "--data-file", "-"],
        input=value.encode(), capture_output=True)
    if created.returncode != 0:
        add = subprocess.run(
            ["gcloud", "secrets", "versions", "add", name, "--project", PROJECT, "--data-file", "-"],
            input=value.encode(), capture_output=True)
        if add.returncode != 0:
            raise SystemExit(f"secret store failed for {name}:\n  create: {created.stderr.decode().strip()}"
                             f"\n  add: {add.stderr.decode().strip()}")
    print(f"  ✓ {name}")


def main():
    if len(sys.argv) != 2:
        print("usage: python local/mint_google_token.py /path/to/client_secret.json")
        sys.exit(1)
    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
    flow.redirect_uri = "http://localhost:8765/"  # loopback; nothing needs to listen here
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

    print(f"\n1) Open this URL in a browser signed in as {OWNER_EMAIL}:\n")
    print(auth_url)
    print("\n2) Click 'Allow'. The browser will then fail to load a 'localhost' page — THAT IS EXPECTED.")
    print("   Copy the ENTIRE URL from the address bar (it starts with http://localhost:8765/?code=...).\n")
    resp = input("3) Paste that full URL here and press Enter:\n").strip()

    flow.fetch_token(authorization_response=resp)
    creds = flow.credentials
    if not creds.refresh_token:
        print("\nNo refresh token returned. Revoke prior access at myaccount.google.com/permissions "
              "and re-run (needs prompt=consent + access_type=offline).")
        sys.exit(2)

    conf = flow.client_config
    print("\nStoring secrets (token is not printed):")
    put_secret("convo-live-google-oauth-refresh-token", creds.refresh_token)
    put_secret("convo-live-google-oauth-client",
               json.dumps({"client_id": conf["client_id"], "client_secret": conf["client_secret"]}))
    print("\n✓ Done. Both secrets are in Secret Manager. Tell the assistant 'done'.")


if __name__ == "__main__":
    main()
