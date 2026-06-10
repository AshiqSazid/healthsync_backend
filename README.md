# HealthSynch Backend

## Setup

1. Copy the sample environment file and fill in the missing secrets locally:

```bash
cp .env.example .env
```

2. Add private local overrides in `backend/.env.local` for secrets you do not want in your local `.env` file:

```bash
cat > .env.local <<'EOF'
SMTP_USERNAME=your-email@example.com
SMTP_PASSWORD=your-google-app-password
OPENAI_API_KEY=your-openai-api-key
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-cloudinary-api-key
CLOUDINARY_API_SECRET=your-cloudinary-api-secret
EOF
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Apply database migrations:

```bash
alembic upgrade head
```

5. Run the API:

```bash
uvicorn app.main:app --reload
```

Swagger UI: `https://health-synch-backend.vercel.app/docs`

## Vercel and Neon Postgres

Use SQLite in your local `backend/.env` for development and configure Neon only in Vercel.

Set these Vercel environment variables for the backend project:

```text
ENVIRONMENT=production
FRONTEND_URL=https://myhealthsynch.com
BACKEND_PUBLIC_URL=https://api.myhealthsynch.com
JWT_REFRESH_COOKIE_DOMAIN=.myhealthsynch.com
DATABASE_URL=postgresql://...-pooler.../neondb?channel_binding=require&sslmode=require
SQLALCHEMY_DATABASE_URI=postgresql://...-pooler.../neondb?channel_binding=require&sslmode=require
DATABASE_URL_UNPOOLED=postgresql://....../neondb?sslmode=require
```

Important:

- Vercel must set `SQLALCHEMY_DATABASE_URI` explicitly. Setting only `DATABASE_URL` is not enough because local development defaults to SQLite unless you opt into `LOCAL_DB_MODE=neon`.
- Use the pooled Neon URL for runtime on Vercel.
- Use `DATABASE_URL_UNPOOLED` or Vercel's `POSTGRES_URL_NON_POOLING` for Alembic/manual operations.
- The app only auto-creates tables for SQLite. PostgreSQL schema changes must go through Alembic.
- `ADMIN_BOOTSTRAP_ENABLED` is disabled by default. Only enable it with an explicit `ADMIN_BOOTSTRAP_PASSWORD` in a private environment.

Run migrations against Neon from a trusted shell or CI runner:

```bash
SQLALCHEMY_DATABASE_URI="$DATABASE_URL_UNPOOLED" alembic upgrade head
```

## Auth and Upload Configuration

- JWT access tokens use `JWT_SECRET` and expire in 15 minutes.
- JWT refresh tokens use `JWT_REFRESH_SECRET` and expire in 7 days.
- Refresh tokens are returned in the JSON body and also set as an `HttpOnly` cookie named `refresh_token`.
- Password reset emails are sent through Google SMTP using `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM_NAME`.
- Local development reset links should use `http://localhost:3000/reset-password?token=...`.
- Production deployments should set `FRONTEND_URL=https://myhealthsynch.com`.
- Google OAuth production deployments should set `BACKEND_PUBLIC_URL=https://api.myhealthsynch.com` and configure the same callback URL in Google Cloud Console.
- If frontend and API run on sibling subdomains, set `JWT_REFRESH_COOKIE_DOMAIN=.myhealthsynch.com` so refresh cookies are shared reliably.
- The password reset email content uses the HealthSynch app name and links to `{FRONTEND_URL}/reset-password?token=...`.
- Cloudinary uploads are limited to `4MB` per file by default through `MAX_UPLOAD_MB`.
- Uploads are stored in Cloudinary under:

```text
healthsynch/users/{sanitized_email}/prescriptions/YYYY/MM/DD/
healthsynch/users/{sanitized_email}/reports/YYYY/MM/DD/
```

## Example Curl Commands

Set a base URL first:

```bash
export API_BASE="https://health-synch-backend.vercel.app/api/v1"
```

### 1. Signup

```bash
curl -X POST "$API_BASE/auth/signup" \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{
    "name": "Abir Islam",
    "email": "abirs25ultra@gmail.com",
    "password": "StrongPass1"
  }'
```

### 2. Login

```bash
curl -X POST "$API_BASE/auth/login" \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{
    "email": "abirs25ultra@gmail.com",
    "password": "StrongPass1"
  }'
```

### 3. Forgot Password

```bash
curl -X POST "$API_BASE/auth/forgot-password" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "abirs25ultra@gmail.com"
  }'
```

### 4. Reset Password

```bash
curl -X POST "$API_BASE/auth/reset-password" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "token": "paste-reset-token-here",
    "new_password": "NewStrongPass1"
  }'
```

### 5. Refresh Tokens Using Cookie

```bash
curl -X POST "$API_BASE/auth/refresh" \
  -b cookies.txt \
  -c cookies.txt
```

### 6. Refresh Tokens Using Body

```bash
curl -X POST "$API_BASE/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "paste-refresh-token-here"
  }'
```

### 7. Logout

```bash
curl -X POST "$API_BASE/auth/logout" \
  -b cookies.txt \
  -c cookies.txt
```

### 8. Current User

```bash
curl "$API_BASE/auth/me" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### 9. Upload Prescription

```bash
curl -X POST "$API_BASE/uploads/prescription" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -F "file=@/absolute/path/to/prescription.jpg"
```

### 10. Upload Reports

```bash
curl -X POST "$API_BASE/uploads/report" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -F "files=@/absolute/path/to/report1.pdf" \
  -F "files=@/absolute/path/to/report2.png"
```

### 11. List My Uploads

```bash
curl "$API_BASE/uploads/my-uploads?type=report&page=1&limit=10" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### 12. Get One Upload

```bash
curl "$API_BASE/uploads/UPLOAD_ID" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### 13. Delete Upload

```bash
curl -X DELETE "$API_BASE/uploads/UPLOAD_ID" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## Notes

- The live API paths in this repository are versioned under `/api/v1`.
- The tracked `backend/.env` is intentionally safe and keeps SQLite as the local default. Put real secrets in `backend/.env.local` or Vercel project env vars.
- Rotate any credentials that were previously committed or shared before this cleanup.
- Set both `DATABASE_URL` and `SQLALCHEMY_DATABASE_URI` in Vercel to the same pooled Neon runtime URL.
- Use `DATABASE_URL_UNPOOLED` only for Alembic/manual operations against Neon.
- Settings load `backend/.env` first and `backend/.env.local` second, so private local secrets can override tracked defaults.
- Existing routes such as `/api/v1/auth/register` and `/api/v1/auth/login/access-token` are still present for backward compatibility.
