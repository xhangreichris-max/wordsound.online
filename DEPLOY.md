# Deploying wordsound.online

One-time setup. After this, every push to `main` builds and deploys
automatically via `.github/workflows/deploy.yml` -- these steps aren't
repeated per-deploy.

## 1. Create the repo and push

Create a **public** repo on GitHub (private repos need GitHub Pro/Team for
Pages). Repo name doesn't matter for any of the steps below -- pick
anything, e.g. `wordsound-online`.

```
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/xhangreichris-max/<repo-name>.git
git push -u origin main
```

## 2. Enable GitHub Pages

Repo -> **Settings -> Pages -> Build and deployment -> Source** ->
**GitHub Actions**.

Do this before the first push finishes, or right after -- the workflow
needs Pages enabled to have somewhere to deploy to. If the first run
fails because of this, re-run it from the Actions tab once Pages is on.

## 3. DNS at your registrar (Namecheap)

Namecheap dashboard -> Domain List -> `wordsound.online` -> **Manage** ->
**Advanced DNS**. Add:

| Type | Host | Value | TTL |
|---|---|---|---|
| A | @ | 185.199.108.153 | Automatic |
| A | @ | 185.199.109.153 | Automatic |
| A | @ | 185.199.110.153 | Automatic |
| A | @ | 185.199.111.153 | Automatic |
| CNAME | www | xhangreichris-max.github.io. | Automatic |

Four apex `A` records, not one -- GitHub Pages load-balances across all
four. Remove any existing `A`, `AAAA`, `CNAME`, or `URL Redirect` record
already sitting on `@` or `www` first; a leftover parking-page redirect is
the most common reason this doesn't take.

## 4. Set the custom domain in GitHub

Repo -> **Settings -> Pages -> Custom domain** -> enter `wordsound.online`
-> **Save**. This is also what (re-)writes `output/CNAME`'s expected
content on GitHub's side -- it must match the `wordsound.online` that
`build.py` writes into `output/CNAME` on every build, or Pages will
reject the custom domain.

## 5. Wait for DNS, then enforce HTTPS

GitHub checks DNS propagation on its own schedule; the Pages settings
page shows a pending/green check status. This can take up to 24 hours,
though it's often much faster. **Enforce HTTPS** stays greyed out and
unclickable until that check passes -- tick it as soon as it's available.
Don't skip this: without it, the site serves over plain HTTP with no
redirect.

## 6. Google Search Console

1. [search.google.com/search-console](https://search.google.com/search-console)
   -> **Add property** -> Domain property -> `wordsound.online`.
2. Verify via **DNS TXT record** (add the TXT record Search Console gives
   you at the same Namecheap Advanced DNS screen as step 3).
3. Once verified, **Sitemaps** -> submit `https://wordsound.online/sitemap.xml`.

Submit the sitemap only after HTTPS is enforced (step 5) -- Search
Console will fetch it over HTTPS, and submitting earlier just means
re-submitting later when the URL that was crawled 404s or redirects.
