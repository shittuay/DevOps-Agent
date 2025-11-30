#!/bin/bash
# Netlify build script for DevOps Agent

echo "Starting build process..."

# Install Python dependencies
echo "Installing Python dependencies..."
python3.11 -m pip install --upgrade pip
python3.11 -m pip install -r requirements.txt

echo "Build completed successfully!"
