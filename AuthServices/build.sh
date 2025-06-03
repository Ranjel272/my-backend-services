#!/usr/bin/env bash
# exit on error
set -o errexit

echo "Starting build script for AuthServices..."

# -----------------------------------------------------------------------------
# Install Microsoft ODBC Driver 17 for SQL Server
# -----------------------------------------------------------------------------
echo "Updating package lists..."
apt-get update -y

echo "Installing prerequisites for Microsoft ODBC Driver..."
# -qq implies -y and makes output quieter
apt-get install -qq curl apt-transport-https gnupg lsb-release

echo "Adding Microsoft GPG key..."
curl -sSL https://packages.microsoft.com/keys/microsoft.asc | apt-key add -

echo "Adding Microsoft APT repository..."
# Determine Debian version for the repository
DEBIAN_VERSION_CODENAME=$(lsb_release -cs 2>/dev/null || echo "bullseye")

if [[ "$DEBIAN_VERSION_CODENAME" != "bullseye" && "$DEBIAN_VERSION_CODENAME" != "bookworm" && "$DEBIAN_VERSION_CODENAME" != "buster" ]]; then
    echo "Detected Debian version '$DEBIAN_VERSION_CODENAME' is not directly supported or detection failed. Defaulting to Bullseye (Debian 11)."
    DEBIAN_VERSION_CODENAME="bullseye"
fi

echo "Using Debian version '$DEBIAN_VERSION_CODENAME' for Microsoft repository."
curl -sSL "https://packages.microsoft.com/config/debian/${DEBIAN_VERSION_CODENAME}/prod.list" > /etc/apt/sources.list.d/mssql-release.list

echo "Updating package lists again after adding new repository..."
apt-get update -y

echo "Installing msodbcsql17 and unixodbc-dev..."
ACCEPT_EULA=Y apt-get install -y -qq msodbcsql17 unixodbc-dev

echo "Verifying ODBC driver installation..."
if odbcinst -q -d -n "ODBC Driver 17 for SQL Server"; then
    echo "ODBC Driver 17 for SQL Server found."
else
    echo "WARNING: ODBC Driver 17 for SQL Server not found after installation attempt. Check odbcinst.ini or driver name."
    echo "Contents of /etc/odbcinst.ini:"
    cat /etc/odbcinst.ini || echo "/etc/odbcinst.ini not found or unreadable."
fi

# -----------------------------------------------------------------------------
# Install Python Dependencies for AuthServices
# (Assumes requirements.txt is in AuthServices/ root)
# -----------------------------------------------------------------------------
echo "Upgrading pip..."
pip install --upgrade pip

echo "Installing Python requirements from requirements.txt..."
pip install -r requirements.txt # This requirements.txt should be specific to AuthServices

echo "Build script for AuthServices finished successfully."