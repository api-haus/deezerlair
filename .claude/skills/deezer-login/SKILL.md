---
name: deezer-login
description: Connect this repo to a Deezer account, or repair a broken connection. Use when a script reports no access token or an OAuth error, when `dz_login.py --check` fails, or when the user asks to log in, re-authorise, switch account, or grant more permissions.
---

# /deezer-login — connect the account

The Deezer login needs a browser and a human. You cannot do it alone. Your job
is to prepare each step, hand the user exactly one thing to do, and take the
answer back.

## First, find out what is actually missing

```bash
python3 scripts/dz_login.py --check
```

- It prints a name and a permission list — the account is connected. Say so
  and stop. Re-run the flow only if the user wants a different account, or if
  `manage_library` or `delete_library` is absent from the list.
- It says no token is stored — go to step 1.
- It says the token is not usable — the token was revoked or the account
  changed its password. Go to step 2; the application registration survives.

## Step 1 — the application (once per machine)

Read `.env` if it exists. If `DEEZER_APP_ID`, `DEEZER_APP_SECRET` and
`DEEZER_REDIRECT_URI` are all filled in, skip to step 2.

Otherwise the user has to register an application. Ask them to open
<https://developers.deezer.com/myapps>, press **Create a new Application**,
and fill the form. Tell them these values, and that the redirect URL must
match to the character:

- Application name: `deezerlair` (any name works)
- Application domain: `localhost`
- Redirect URL after authentication: `http://localhost:8080/deezerlair`

Deezer allows one redirect URL per application, so it cannot be changed later
without editing both places. When they come back with the Application ID and
the Secret Key, write `.env` from `.env.example` yourself:

```bash
cp .env.example .env && chmod 600 .env
```

Then put the two values in. Never print the secret back to the chat.

## Step 2 — the login link

```bash
python3 scripts/dz_login.py --url
```

Give the user that URL and this instruction, in your own words:

> Open the link, press **Allow**, and the browser will land on a page that
> fails to load. That failure is expected — nothing is listening on that
> address. Copy the whole address out of the address bar and paste it back
> here.

The page fails because the redirect points at a local port that no server is
holding. The part that matters is the `code=…` parameter in the address.

## Step 3 — take the code back

```bash
python3 scripts/dz_login.py --code '<the address they pasted>'
```

Quote the argument — the address contains `&`. The script accepts the full
address, a bare query string, or the code on its own.

The code expires in a few minutes and works once. If the exchange fails, go
back to step 2 and produce a fresh link rather than reusing the old one.

On success it prints the account name, the granted permissions, and the path
of the token file. Repeat that to the user, without the token itself.

## When the user runs their own terminal

If the user says they are at the keyboard and would rather do it themselves,
one command covers steps 2 and 3:

```bash
python3 scripts/dz_login.py --serve
```

It opens the browser, catches the redirect on `localhost:8080`, and stores the
token. Do not run this yourself — it blocks until a browser answers, and the
browser it opens may not be on the user's screen.

## Afterwards

Confirm the connection and leave the account ready to work with:

```bash
python3 scripts/dz_login.py --check
python3 scripts/dz_pull.py --snapshot
```

If `manage_library` or `delete_library` is missing from the permission list,
the write scripts will fail. That means a permission was declined on the
consent page. Go back to step 2 and tell the user to accept all of them.
