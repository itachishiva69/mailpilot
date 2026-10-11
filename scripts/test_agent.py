"""Smoke test for general chat; does not access Gmail."""
from app.email_agent import ask_mailpilot

if __name__ == "__main__":
    print(ask_mailpilot("What is an AI agent?"))
