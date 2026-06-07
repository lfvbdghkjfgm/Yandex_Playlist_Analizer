#!/bin/bash
set -e

# Start ollama server in background
ollama serve &
OLLAMA_PID=$!

# Wait for ollama to be ready
echo "Waiting for ollama to be ready..."
sleep 10

# Pull the model
echo "Pulling llama3.1 model..."
ollama pull llama3.1

# Keep ollama running
wait $OLLAMA_PID
