FROM python:3.11-slim

# Install dependencies for pyodbc and ODBC Driver 17
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    gnupg \
    curl \
    unixodbc-dev \
    libpq-dev \
    libsasl2-dev \
    libssl-dev \
    libffi-dev \
    libodbc1 \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/10/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql17 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy your project files
COPY . .

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Expose port for FastAPI
EXPOSE 10000

# Run the FastAPI app with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
