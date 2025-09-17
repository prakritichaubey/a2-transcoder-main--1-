Assignment 1 - REST API Project - Response to Criteria
================================================

Overview
------------------------------------------------

- **Name:** Kimiya Heidarzadeh Naeini
- **Student number:** n11668075
- **Application name:** My Video Transcoder
- **Two line description:** This REST API allows user to upload and transcode in different resolutions (360, 480, 720, 1080p). Users can also view the history of their uploads and jobs in detail, while the admin has the privilege of accessing everyone's history.

Core criteria
------------------------------------------------

### Containerise the app

- **ECR Repository name:** n11668075-a1-transcoder
- **Video timestamp:**
- **Relevant files:**
    - Dockerfile
    - .dockerignore
    - requirements.txt

### Deploy the container

- **EC2 instance ID:** i-0a37cd4273b65b80b (t3.small, Ubuntu 24.04)
- **Video timestamp:**

### User login

- **One line description:** JWT authentication with admin, kimia, and sara accounts (hard-coded); tokens secure API endpoints
- **Video timestamp:**
- **Relevant files:**
    - auth.py (JWT logic)
    - main.py (dependency injection)

### REST API

- **One line description:** Exposes endpoints for video upload, transcoding, job history, and output retrieval.
- **Video timestamp:**
- **Relevant files:**
    - main.py
    - jobs.py
    - videos.py

### Data types

- **One line description:** The app handles both structured (SQLite DB) and unstructured (video files) data.
- **Video timestamp:**
- **Relevant files:**
    - models.py
    - jobs.py 
    - /app/data (mounted volume)

#### First kind

- **One line description:** job + video metadata stored in SQLite DB
- **Type:** Structured
- **Rationale:** Needed for tracking job status and history
- **Video timestamp:**
- **Relevant files:**
    - models.py
    - jobs.py

#### Second kind

- **One line description:** Uploaded and transcoded video files stored in filesystem.
- **Type:** Unstructured
- **Rationale:** needed to store original videos and generated renditions.
- **Video timestamp:**
- **Relevant files:**
    - /app/data
    - ffmpeg_runner.py

### CPU intensive task

 **One line description:** Video transcoding using FFmpeg with libx264, slow/very slow presets, and multiple renditions.
- **Video timestamp:** 
- **Relevant files:**
    - ffmpeg_runner.py
    - jobs.py

### CPU load testing

 **One line description:** Automated curl/hey requests triggered concurrent transcodes; CPU sustained ≥90% for ~5 minutes, verified via mpstat and AWS Monitoring.
- **Video timestamp:** 
- **Relevant files:**
    - mpstat 5 70 | tee ~/cpu_log.txt (terminal CPU log)
    - AWS EC2 Monitoring tab (CPU Utilisation graph)

Additional criteria
------------------------------------------------

### Extensive REST API features

- **One line description:** /jobs/history supports pagination and filtering by user; endpoints return structured JSON with job status, owner, and timestamps.
- **Video timestamp:**
- **Relevant files:**
    - jobs.py (job history query and filtering)
    - models.py (job schema and DB integration)

### External API(s)

- **One line description:** Not attempted
- **Video timestamp:**
- **Relevant files:**
    - 

### Additional types of data

- **One line description:** In addition to core video files and job records, the app manages user authentication data (JWT tokens/roles) and transcode specifications (renditions: width, height, crf, suffix) stored in JSON format.
- **Video timestamp:**
- **Relevant files:**
    - auth.py (JWT tokens, role-based access)
    - jobs.py (rendition specs stored as JSON in DB)
    - models.py (user/job models)

### Custom processing

- **One line description:** FFmpeg pipeline modified with heavy presets (veryslow, placebo) and scaling to force CPU load
- **Video timestamp:**
- **Relevant files:**
    - ffmpeg_runner.py

### Infrastructure as code

- **One line description:** Not attempted (manual deployment with docker run)
- **Video timestamp:**
- **Relevant files:**
    - 

### Web client

- **One line description:** Custom web UI served from /; supports login, video upload, job monitoring, and preview
- **Video timestamp:**
- **Relevant files:**
    - /static (frontend files)
    - main.py (StaticFiles mount)

### Upon request

- **One line description:** Not attempted
- **Video timestamp:**
- **Relevant files:**
    - 