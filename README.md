# 🧠 Trocare - RAG Backend (Production Ready)

This is a **RAG (Retrieval-Augmented Generation) backend** supports various file format built with **FastAPI**, using **MySQL**, **Pinecone**, and **Hugging Face Transformers**. 
---

## 🚀 Features

- 🔐 JWT-based Authentication (Login/Signup)
- 📂 Document Upload per User
- 📄 Document Parsing, Embedding & Storage in Pinecone
- 🧠 RAG-based Querying
- 🐳 Fully Dockerized for Local or Cloud Deployment

---

## 📦 Folder Structure

```
.
├── app/                      # Core FastAPI application
├── Dockerfile                # Backend container definition
├── docker-compose.yml        # Services: backend + MySQL
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
└── README.md                 # Project documentation
```

---

## ⚙️ Getting Started (via Docker)

### ✅ Step 1: Clone the Repository

```bash
git clone https://github.com/Bhadri2015-SB/Trocare.git
cd Trocare
git checkout -b version-1 origin/version-1
```

### ✅ Step 2: Create a `.env` file

```bash
cp .env.example .env
# Then open and edit values as needed
```

### ✅ Step 3: Run the App

```bash
docker-compose up
```

> This will:
- Pull backend from Docker Hub: `bhadri2919/trocare-backend:v1`
- Pull MySQL official image
- Start everything in containers

---

## 📡 API Access

Once running, visit the Swagger docs:
```
http://localhost:8000/docs
```

You can test:
- `/register` & `/login`
- `/api/upload`
- `/api/initiate-file-process`
- `/query-retriever` (RAG)

---

## 📤 Docker Images

| Image              | Source                       |
|-------------------|------------------------------|
| Backend API        | [`bhadri2919/trocare-backend`](https://hub.docker.com/r/bhadri2919/trocare-backend) |
| MySQL              | [`mysql:8`](https://hub.docker.com/_/mysql) (official)

---

## 🧹 Clean Up

To stop and remove the containers:

```bash
docker-compose down
```

