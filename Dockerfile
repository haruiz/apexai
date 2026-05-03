# Stage 1: Build the UI
FROM node:20-alpine AS ui-builder
WORKDIR /app
COPY ui ./ui
WORKDIR /app/ui
RUN npm install
RUN npm run build:package

# Stage 2: Telemetry Server
FROM python:3.11-slim
WORKDIR /app

# Install uv
RUN pip install uv

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY src/apexai ./src/apexai
COPY data ./data

# Install backend dependencies
RUN uv sync --frozen

# Copy the static UI build from stage 1
COPY --from=ui-builder /app/src/apexai/ui/static ./src/apexai/ui/static

# Set port environment variable (Cloud Run defaults to 8080)
ENV PORT=8080
EXPOSE ${PORT}

# Run the server using bash to properly expand the glob for *.vbo files
CMD ["bash", "-c", "/app/.venv/bin/apexai-server --source vbo --vbo-file ./data/*.vbo --autostart --loop --port ${PORT}"]
