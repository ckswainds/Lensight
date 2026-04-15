# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Create a user with UID 1000 (Required by Hugging Face Spaces)
RUN useradd -m -u 1000 user

# Set environment variables
ENV PATH="/home/user/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=7860

# Install minimal build tools if required by dependencies (e.g. for PyPDF, Pandas)
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

# Switch to the non-root user
USER user

# Set working directory
WORKDIR /home/user/app

# Copy requirements first (to cache the pip install step)
COPY --chown=user:user requirements.txt .

# Install dependencies in the user's home directory
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy the rest of the application files
COPY --chown=user:user . .

# Explicitly ensure data and stream directories exist with correct permissions
RUN mkdir -p /home/user/app/data/uploads \
             /home/user/app/data/raw \
             /home/user/app/data/processed/streams \
             /home/user/app/data/vector_store \
             /home/user/app/logs

# Expose the standard port Hugging Face looks for
EXPOSE 7860

# Start Uvicorn
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
