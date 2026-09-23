# Connecting a company email address

We have a piece of software that finds business leads and writes an email to
each one. A person reads every email and approves it; only then is it sent. The
emails go out from **one company email address**, and this page is about giving
the software permission to send from that address.

**Nobody's password is shared.** Google has an official way to grant this
(the same one used by Outlook, Superhuman or any mail app), and it can be taken
away at any time from the account's security page.

It takes about 15 minutes. Everything happens in Google Cloud Console, signed
in as the mailbox we will send from.

## What I need back from you

1. **The email address** we will send from, for example `sales@company.com`.
2. A **Client ID** — a long line that ends in `.apps.googleusercontent.com`.
3. A **Client secret** — a shorter line that usually starts with `GOCSPX-`.
4. **15 minutes with you** (or a screen share) for one sign-in at the end,
   which only you can do because it asks for the mailbox's password. I never
   see the password.

Please do **not** send the client secret over WhatsApp or plain email. Put it
in a password manager and share it from there, or read it out on a call, or
type it into our software's settings yourself.

## Step 1 — Choose the address

Pick the mailbox the emails should come from. It is usually a real person's
address, because replies come back to it.

- A **Google Workspace** address (company domain) is what we want.
- If it is a personal `@gmail.com` address, tell me first. It still works, but
  Google then makes the connection expire every 7 days, so we would rather not.

## Step 2 — Open Google Cloud Console

1. Sign in to Google **as that mailbox** (or as an admin of the company's
   Google Workspace).
2. Go to **console.cloud.google.com**.
3. At the top left, click the project dropdown, then **New Project**.
4. Name it `Lead Engine` and click **Create**.
5. Check that the new project is the one showing at the top.

If a project already exists for this, use it instead of making a new one.

## Step 3 — Turn on Gmail

1. In the search box at the top, type **Gmail API** and open it.
2. Click **Enable**.

That is the switch that lets anything in this project touch Gmail at all.

## Step 4 — Say what the app is

In the left menu, open **APIs & Services** (in newer accounts this section is
called **Google Auth Platform**).

1. Open **OAuth consent screen** (or **Branding**).
2. If it asks **who can use the app**, choose **Internal**. That means only
   people inside the company, which is what we want.
3. If **Internal** is greyed out, the address is not a Google Workspace one.
   Choose **External** instead, and tell me: there is one extra step at my end.
4. For **App name**, put `Lead Engine`.
5. For **User support email** and **Developer contact email**, put the same
   mailbox.
6. Save.

## Step 5 — Create the permission slip

1. Still under **APIs & Services**, open **Credentials** (or **Clients**).
2. Click **Create credentials** → **OAuth client ID**.
3. **Application type**: choose **Desktop app**.
4. **Name**: `Lead Engine`.
5. Click **Create**.

A box appears with the **Client ID** and the **Client secret**.

- If the box only shows the Client ID, click **Download JSON**. The secret is
  inside that file, on the line that starts with `"client_secret"`.
- You can always come back later: **Credentials** → click the client's name.

**Send me both.** See the safety note at the top about how.

## Step 6 — Only if your Workspace blocks new apps

Most companies can skip this. Some Google Workspace accounts are set up so that
new apps must be approved by an admin first. If that is the case here, an admin
needs to:

1. Open **admin.google.com** → **Security** → **Access and data control** →
   **API controls** → **Manage third-party app access**.
2. Click **Configure new app** → **OAuth App Name Or Client ID**.
3. Paste the **Client ID** from Step 5, select the app, and set it to
   **Trusted**.

If you are not sure, skip this. We will find out in the last step, and it takes
two minutes to come back and do it.

## Step 7 — The one sign-in (together, 2 minutes)

This is the part only you can do, because it asks for the mailbox's password.
I will start it on my side; a normal Google sign-in page opens in a browser.

1. You sign in as the sending mailbox.
2. Google shows what is being allowed: **read, send and manage mail for that
   mailbox**, and nothing else. No other Google service is included.
3. Click **Continue**.

That is it. The software can now send from that address.

## What this permission actually allows, and how to remove it

- It covers **that one mailbox only**: sending emails, and reading replies so
  the team can see them in one place. It does not touch Drive, Calendar,
  Contacts, or anyone else's mail.
- It can be switched off at any time at **myaccount.google.com** →
  **Security** → **Your connections to third-party apps & services** → the app
  → **Remove access**. Deleting the client in Google Cloud does the same.
- Our software sends **at most 35 emails a day** from the address, and every
  email is read and approved by a person first. Google's own limit for a
  Workspace account is 2,000 a day, so we stay far below it.

## The checklist, once more

1. The sending email address
2. Client ID (ends in `.apps.googleusercontent.com`)
3. Client secret (starts with `GOCSPX-`), shared safely
4. A 15-minute slot for the sign-in in Step 7
5. Whether it is a Google Workspace address or a personal Gmail one
