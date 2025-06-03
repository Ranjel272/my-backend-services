#!/usr/bin/env bash
# exit on error
set -o errexit

echo "Starting build script for AuthServices..."

echo "Ensuring apt list directories exist..."
# Create the directory. The -p flag means it won't error if it exists.
# We might not have permission to create /var/lib/apt/lists itself if it's on a read-only fs,
# but if only 'partial' is missing and its parent is writable, this could help.
mkdir -p /var/lib/apt/lists/partial || echo "Could not create /var/lib/apt/lists/partial, might be read-only or already exist."

# -----------------------------------------------------------------------------
# Install Microsoft ODBC Driver 17 for SQL Server
# -----------------------------------------------------------------------------
echo "Updating package lists..."
apt-get update -y # This is the command that failed previously

echo "Installing prerequisites for Microsoft ODBC Driver..."
# Using --no-install-recommends to be leaner
apt-get install -y --no-install-recommends curl apt-transport-https gnupg lsb-release

echo "Adding Microsoft GPG key..."
curl -sSL https://packages.microsoft.com/keys/microsoft.asc | apt-key add -

echo "Adding Microsoft APT repository..."
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
# Using --no-install-recommends
ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 unixodbc-dev

echo "Verifying ODBC driver installation..."
if odbcinst -q -d -n "ODBC Driver 17 for SQL Server"; then
    echo "ODBC Driver 17 for SQL Server found."
else
    echo "WARNING: ODBC Driver 17 for SQL Server not found after installation attempt. Check odbcinst.ini or driver name."
fi
echo "odbcinst.ini location and content (odbcinst -j):"
odbcinst -j # Shows DSN_FILE_PATH, DRIVER_FILE_PATH for system and user
echo "System /etc/odbcinst.ini content:"
cat /etc/odbcinst.ini || echo "/etc/odbcinst.ini not found or unreadable."
echo "Listing contents of /opt/microsoft/msodbcsql17/lib64/ if it exists:"
ls -l /opt/microsoft/msodbcsql17/lib64/ || echo "/opt/microsoft/msodbcsql17/lib64/ not found."

# -----------------------------------------------------------------------------
# Install Python Dependencies for AuthServices
# -----------------------------------------------------------------------------
echo "Upgrading pip..."
pip install --upgrade pip
echo "Installing Python requirements from requirements.txt..."
pip install -r requirements.txt

echo "Build script for AuthServices finished successfully."