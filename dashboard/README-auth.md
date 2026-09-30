# Setting up "Continue with Google"

Email/password login already works with no setup. Google login is optional and
stays hidden on `/login` and `/signup` until you complete these steps and
restart the dev server.

## 1. Create a Google OAuth client

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create
   a project (or pick an existing one).
2. Go to **APIs & Services > OAuth consent screen**. Choose **External**,
   fill in an app name, your email, and save (you can leave it in "Testing"
   mode while developing -- that's fine for a hackathon demo).
3. Go to **APIs & Services > Credentials > Create Credentials > OAuth client ID**.
4. Application type: **Web application**.
5. Under **Authorized redirect URIs**, add:
   - `http://localhost:3000/api/auth/callback/google` (local dev)
   - `https://<your-deployed-domain>/api/auth/callback/google` (once deployed)
6. Click **Create**. Copy the **Client ID** and **Client Secret**.

## 2. Add them to this project

Edit `dashboard/.env.local` (already gitignored -- never commit real secrets):

```
GOOGLE_CLIENT_ID=<paste here>
GOOGLE_CLIENT_SECRET=<paste here>
```

Restart `npm run dev`. A "Continue with Google" button will now appear on
`/login` and `/signup` automatically -- the app checks which providers are
actually configured (via Auth.js's built-in `/api/auth/providers`) rather than
assuming, so nothing breaks if these are left blank.

## How it fits together

- First-time Google sign-in creates a row in the same local `users` table
  email/password accounts use (see `src/lib/db.ts`), with `password_hash`
  left `NULL` and `provider = 'google'` -- so favorites, notes, and alert
  preferences all key off one consistent user id no matter how someone signed
  in.
- Session handling for both methods is entirely owned by Auth.js
  (`src/auth.ts`) via its own signed JWT cookie -- there is no separate,
  custom session system anymore.
