"""Mint a signed bearer token for the MCP servers: python scripts/issue_token.py <subject> researcher|admin"""
import sys

from lisa.common.auth import issue_token
from lisa.common.config import load_auth_settings

print(issue_token(load_auth_settings(), sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "researcher"))
