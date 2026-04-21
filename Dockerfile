FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npx vite build

FROM python:3.12-slim
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy backend
COPY tools/ ./tools/
COPY config.yaml pyproject.toml llmbase.py ./
COPY wsgi.py /app/wsgi.py
RUN pip install --no-cache-dir -e .

# Copy built frontend
COPY --from=frontend-build /app/static/dist ./static/dist

# Create data directories
RUN mkdir -p raw wiki/_meta wiki/concepts wiki/outputs

# Expose port
EXPOSE 5555

# Use gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:5555", "--workers", "2", "--timeout", "300", "wsgi:app"]
