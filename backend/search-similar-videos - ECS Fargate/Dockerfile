FROM public.ecr.aws/docker/library/python:3.11-slim

# Set working directory in container
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Install ca-certificates and wget for downloading DocumentDB certificate
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates wget && \
    rm -rf /var/lib/apt/lists/*

# Download DocumentDB TLS certificate bundle using wget
RUN wget -O /app/global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem && \
    chmod 644 /app/global-bundle.pem

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install -r requirements.txt

# Copy application code
COPY main.py .
COPY routes.py .
COPY services.py .
COPY seed_users.py .
COPY startup.sh .

# Make startup script executable
RUN chmod +x startup.sh

# Expose port
EXPOSE 8000

# Run startup script (seeds users, then starts app)
CMD ["./startup.sh"]
