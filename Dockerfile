FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . /app

# Expose port
EXPOSE 8080

# Use gunicorn to run the Flask app
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app", "--workers", "1", "--threads", "4"]
