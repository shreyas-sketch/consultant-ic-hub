# End-to-end journeys

Real user journeys through the real UI in Chromium: a consultant on desktop, clients on a phone-sized screen. Each journey fails on any page error, console error or 5xx response, and saves a screenshot where it stopped.

| File | Journeys |
|---|---|
| `j01_login_and_leads.cjs` | WhatsApp-code login through the form, uninvited number, deep link after login, new lead, public lead form |
| `j02_money.cjs` | request a payment → client claims on a phone → consultant confirms → receipt and invoice PDFs; numbering, credit note, paid-invoice lock |
| `j03_client_file.cjs` | client file on a phone: review → choose package → sign with a code → pay → done |
| `j04_booking_portal.cjs` | booking page from Mumbai and Dubai time zones (saved instant must match the slot picked); client portal login, invoices, message |
| `j05_security_ui.cjs` | hostile HTML in an AI draft and in a portal message must never execute |
| `j06_work.cjs` | log time → invoice it; approve a draft; member/collaborator visibility; onboarding; settings; staff admin limits; chat |

## Run

The security journeys plant data straight into MongoDB, so run the QA server on a real database:

```bash
docker run -d --name qa-mongo -p 27017:27017 mongo:7 --replSet rs0
```

```bash
docker exec qa-mongo mongosh --quiet --eval 'rs.initiate({_id:"rs0",members:[{_id:0,host:"localhost:27017"}]})'
```

```bash
QA_MODE=true QA_DB=mongo MONGO_URL="mongodb://localhost:27017/?replicaSet=rs0&directConnection=true" DB_NAME=pos_e2e python scripts/qa_server.py
```

```bash
cd scripts/e2e && node journeys.cjs            # all journeys; or: node journeys.cjs money
```

Needs `playwright` resolvable by Node (e.g. `npm i -g playwright`, then `NODE_PATH=$(npm root -g)`).
Login codes have a 30-second resend cooldown per phone, so wait 30 s before rerunning the same journey.

`explore.cjs` and `peek.cjs` print a screen's (or a dialog's) buttons and fields, which helps when writing a new journey.
