# 🔍 **CodeLens-AI Powered Code Review & Repository Intelligence**
A full-stack web application that uses Claude AI to perform senior-engineer-level code analysis. Submit a snippet for a production-readiness review, or connect your GitHub account to explore any repository file-by-file and understand its architecture.
# 🌐 Live Demo: https://code-lens-lake.vercel.app/

---
## **Problem Statement**
Most developers — especially those learning with AI coding tools — ship code they don't fully understand. Copy-pasting from ChatGPT, Stack Overflow, or tutorials creates codebases full of unreviewed logic, silent bugs, and security vulnerabilities that nobody caught because nobody read the code carefully. According to the Stack Overflow Developer Survey 2024, 70% of developers admit they don't fully understand the AI-generated code they use, and 85% of developers at small companies have no formal code review process. Junior developers rarely have access to a senior engineer who will explain exactly what is wrong and why. CodeLens solves this by making that review available to anyone, on any code, instantly.

---

## **Approach**
### **Key Idea**
- Accept raw code snippets or GitHub repository files as input
- Run structured AI analysis using Claude claude-opus-4-5 with engineered prompts that enforce strict output formatting
- Parse the AI response into discrete sections and store results in PostgreSQL for caching
- Serve structured feedback through a REST API to a split-panel React frontend

---

## **Features**
### **Snippet Review**
Users paste any code snippet and receive a full production-readiness report:

- Plain-English explanation of what the code does step by step
- Numbered list of every bug with corrected code snippets
- Concrete improvement suggestions with examples
- Big O time and space complexity analysis
- Dedicated security section covering OWASP Top 10
- Production readiness score from 0 to 100 with weighted reasoning

### **Repo Intelligence**
Users connect their GitHub account and explore any repository:

- Full file tree browser with folder collapse and expand
- Per-file analysis covering purpose, technologies used, programming concepts, and senior engineer perspective
- Repository architecture summary covering components, tech stack, and entry points for new developers

---

## **ML/AI Architecture**
The system follows a modern AI pipeline:

1. **Frontend (React)**: User submits code or selects a file from their GitHub repo
2. **Flask Backend**: Receives the request, validates the user's Anthropic API key, checks the PostgreSQL cache
3. **Prompt Engineering**: Structured prompt with strict section headers sent to Claude claude-opus-4-5
4. **Inference**: Claude returns a plain-text response with labeled sections
5. **Parsing**: A regex-based parser extracts each section, strips markdown artifacts, and sanitizes AI self-talk
6. **Storage**: Result written to PostgreSQL for future cache hits
7. **Response**: Structured JSON returned to the frontend and rendered as collapsible sections
---

## **Feature Engineering - Prompt Design**
Rather than sending raw code with a vague instruction, each prompt is engineered to produce deterministic, structured output:

- **Section headers** — EXPLANATION:, BUGS:, SCORE:, SCORE_REASONING: enforce a parseable format
- **Weighted scoring rubric** — the model is instructed to weight correctness 30%, security 25%, performance 20%, readability 15%, best practices 10%
- **Per-bug structure** — each bug must include what it is, what breaks at runtime, and a corrected snippet
- **System prompt persona** — a 15-year senior engineer persona is set at the system level to anchor tone and depth
- **File analysis sections** — SUMMARY:, TECH:, CONCEPTS:, PURPOSE: force the model to reason across four distinct dimensions per file

--- 

## **Tech Stack**

### **Backend**
| Technology | Purpose |
|------------|---------|
| Python 3.11 | Primary backend language |
| Flask 3.1 | HTTP routing and request handling |
| Gunicorn | WSGI production server on Render |
| SQLAlchemy 2.0 | ORM for PostgreSQL database abstraction |
| PostgreSQL (Supabase) | Persistent storage for submission and analysis cache |
| Anthropic SDK 0.86 | Python client for Claude claude-opus-4-5 |
| Flask-CORS | Cross-origin request handling between Vercel and Render |
| Flask-Limiter | Rate limiting at 10 requests per hour per IP |
| Requests | HTTP client for GitHub API calls |
| python-dotenv | Environment variable management |

### **Frontend**
| Technology | Purpose |
|------------|---------|
| React 19 | Component-based UI with hooks |
| Tailwind CSS 3 | Utility-first styling |
| PostCSS + Autoprefixer | CSS processing and cross-browser compatibility |
| Create React App 5 | Build tooling, webpack, Babel |

### **Infrastructure**
| Service | Purpose |
|---------|---------|
| Vercel | Frontend hosting with automatic deploys from GitHub |
| Render | Backend hosting, Gunicorn, 2 workers, 180s timeout |
| Supabase | Managed PostgreSQL, session pooler for IPv4 |
| GitHub | Version control and OAuth provider |

---

## **Project Structure**

CodeLens/
├── backend/
│   ├── app.py                  # Flask application, /review endpoint
│   ├── github_routes.py        # GitHub OAuth and repo API blueprint
│   ├── database.py             # SQLAlchemy engine and session factory
│   ├── models.py               # Submission ORM model
│   ├── requirements.txt
│   └── .env
├── frontend/
│   ├── src/
│   │   ├── App.js              # Full application — both modes, all components
│   │   └── index.js
│   ├── tailwind.config.js
│   └── package.json
└── README.md
---

## **How to Run**

1. **Set up the backend**
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Create `backend/.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://...
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
SECRET_KEY=any-random-string
FRONTEND_URL=http://localhost:3000
python app.py

2. **Set up the frontend**
cd frontend
npm install
npm start
```

Create `frontend/.env`:
```
REACT_APP_API_URL=http://127.0.0.1:5000

---

## **Key Engineering Decisions**
- **BYOK (Bring Your Own Key)**: Users supply their own Anthropic API key. It is stored only in React component state, passed per-request via X-Api-Key header, and never written to the database. This eliminates server-side API cost liability entirely.
- **Multi-level caching**: Snippet reviews are cached by exact code match in PostgreSQL. File analyses are cached by SHA-256 content hash. GitHub token validation is cached in-memory with a five-minute TTL.
- **GitHub OAuth via URL params**: After authorization, the access token is passed to the frontend via URL query parameters, immediately read into React state, and the URL is cleaned — the token never touches localStorage or a database.
- **Flask Blueprint architecture**: GitHub routes are modularized into a separate Blueprint, keeping app.py focused on the core review logic.
- **Structured LLM output parsing**: Prompts enforce plain-text section headers. A regex-based parser extracts each section independently and sanitizes markdown artifacts before storage or display.

---

## **Limitations**
- **Snippet size cap**: Reviews are limited to 5000 characters to control token cost and response time
- **Repo sampling**: Architecture analysis samples up to 8 source files — very large monorepos may not get full coverage
- **Cache sensitivity**: Caching is by exact code match, not semantic similarity — minor formatting changes bypass the cache
- **Cold starts**: The free tier on Render spins down after inactivity, causing a 30–60 second delay on the first request
- **Synthetic validation**: AI reviews are probabilistic — they reflect model judgment, not a compiler or static analysis tool
  
---

## **Future Improvements**
- **Static analysis pipeline**: Integrate Bandit, Pylint, and Semgrep to combine deterministic linting with AI explanation — the AI explains what the linter found rather than guessing
- **GitHub PR review bot**: Webhook pipeline that automatically analyzes opened pull requests and posts inline comments via the GitHub API
- **User accounts and history**: JWT authentication with per-user submission history and score trend tracking over time
- **RAG pipeline**: Vector embeddings for semantic search across entire repositories using Pinecone
- **Docker + AWS**: Full containerization with EC2, RDS, and CloudFront for production-grade deployment
- **SHAP integration**: Replace weighted rubric scoring with SHAP values for more granular, mathematically grounded feature attribution

---

## **Security Notes**
- GitHub access tokens are never persisted — session memory only, cleared on page reload
- Anthropic API keys are never stored server-side — passed per-request via a custom header
- Rate limiting at 10 requests per hour per IP prevents abuse of AI endpoints
- CORS restricted to known frontend origins via environment variable
- All secrets managed via environment variables, never hardcoded in source

---

## **Disclaimer**
This project is for educational and portfolio purposes. AI code reviews are probabilistic and reflect model judgment — they should not be used as the sole basis for security audits or production deployment decisions.

---

## **Author**
**Alvin Chen** 
Brown University — Applied Mathematics & Computer Science
