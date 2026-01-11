# HTTPServer

## Overview
The HTTPServer module provides a RESTful API interface for the forensics analysis tool. Built on Crow and Boost.Asio, it allows users to submit analysis tasks asynchronously and query results via HTTP endpoints.

## Features
- **RESTful API**: Standard endpoints for task management.
- **Asynchronous Processing**: Non-blocking task submission and execution via `TaskManager`.
- **JSON Support**: All requests and responses use JSON format.
- **Lightweight**: fast and efficient routing using Crow.

## Components
- **Core**:
  - `HTTPserver`: Defines API routes and handles HTTP requests.
- **Helpers**:
  - `TaskManager`: Manages the lifecycle and status of analysis tasks.
  - `SQLiteHelper`: Assists in querying analysis results for API responses.

## Usage

### Start Server
```bash
./forensic_analyzer --http-server 8080
```

### API Endpoints
- **Create Task**: `POST /tasks`
  ```json
  { "image_path": "/path/to/image.e01" }
  ```
- **Get Status**: `GET /tasks/{id}`
- **Get Results**: `GET /tasks/{id}/results`

## Dependencies
- **Crow**: C++ Microframework for Web.
- **Boost.Asio**: For asynchronous I/O.
- **nlohmann/json**: For JSON serialization/deserialization.
