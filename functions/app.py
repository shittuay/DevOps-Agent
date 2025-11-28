"""
Netlify Serverless Function wrapper for Flask app
"""
import sys
import os

# Add parent directory to path to import app
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app
import serverless_wsgi

def handler(event, context):
    """
    Netlify Function handler for Flask app
    """
    return serverless_wsgi.handle_request(flask_app, event, context)
