# PHET-Digital

## Run it in VS Code on Windows

1. Extract the ZIP. In VS Code, choose **File → Open Folder** and select the extracted folder containing `app.py`.
2. Open **Terminal → New Terminal**. Run these PowerShell commands with Python 3.10 or newer installed.

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m flask --app app run --debug
   ```

3. Open http://127.0.0.1:5000 in your browser. If `py` is unavailable, use `python -m venv .venv` for the first command.

## Where to edit

- `app.py` contains the routes, packages, portfolio entries, and SQLite order handling.
- `templates/base.html` contains the shared header, footer and WhatsApp button.
- `templates/home.html`, `services.html`, `portfolio.html`, and `order.html` contain the four pages.
- `static/style.css` controls the colours, mobile layout and desktop breakpoints.
- `static/images/` holds the service photos and flyer sample.
- `static/order.js` displays the selected package's 50% deposit.

When the CV promo ends, set `CV_PROMO_ACTIVE = False` in `app.py` and restart the app. The regular prices will apply automatically.

## Try a test order

1. Go to **Services** and select **CV Revamp Premium**. Check that **Order** opens with the package selected and a deposit of R50.
2. Use a test name and phone number such as `082 123 4567`. Submit the form. WhatsApp opens with the order reference and package ready to send. You can close the chat without sending it.
3. Open a second VS Code terminal and inspect your test order.

   ```powershell
   .\.venv\Scripts\python.exe -c "import sqlite3; db = sqlite3.connect('instance/orders.sqlite3'); print(db.execute('SELECT id, name, package, price_rand, notes FROM orders').fetchall())"
   ```

SQLite creates `instance/orders.sqlite3` on the first valid order. Keep that folder private because it stores customer contact details. PayShap, SnapScan and bank transfers are arranged in the WhatsApp conversation. For PayShap, share your receiving details with the customer after confirming the order.

## View a customer's order details

Match the reference from the customer's WhatsApp message to their saved website form. In a second VS Code PowerShell terminal, run:

```powershell
.\.venv\Scripts\python.exe -m flask --app app orders show 2
```

Replace `2` with the reference number. The command shows the customer name, WhatsApp number, selected package, saved price, service-specific answers and notes. If the customer ordered from the hosted site, run the command in the hosting environment against that site's database.

## Check mobile after each change

Open browser DevTools and toggle the device toolbar. Check all four pages at 320 px and around 390 px. Confirm that the navigation fits, the WhatsApp shortcut stays reachable, and the keyboard and form fields work on a phone. Run a test order before publishing changes.

Confirm catalogue timelines with customers before taking their deposits.

## Collect and publish feedback

Once you have delivered the work, open a VS Code terminal on the machine running the site. Create a private, single-use link. Replace the example address with your site's actual HTTPS address.

```powershell
.\.venv\Scripts\python.exe -m flask --app app feedback invite --base-url https://your-site.example
```

The first client can use this command even if they ordered through WhatsApp. For an order already in SQLite, append `--order-id 123` using the actual order reference. Copy the generated feedback link and send it to the client on WhatsApp. For testing on your own computer, use `--base-url http://127.0.0.1:5000`. A localhost link only works on your computer.

After the client submits their review with permission to publish it, check pending feedback and approve the entry you want to show. Replace `1` with the feedback ID printed by the pending command.

```powershell
.\.venv\Scripts\python.exe -m flask --app app feedback pending
.\.venv\Scripts\python.exe -m flask --app app feedback moderate 1 approve
```

Use `reject` in place of `approve` to keep that review off the website. Approved reviews appear on the next homepage refresh. Customers can send private feedback directly on WhatsApp. For a hosted site, run these commands in the hosting environment against the same persistent SQLite database the website uses.

## Switch to your WhatsApp Business number

The website defaults to the PHET-Digital business number, 065 506 5477. If you previously set a different number in your terminal or hosting settings, update that override. Use international format with digits only. For South Africa, replace the leading zero with 27.

```powershell
$env:WHATSAPP_NUMBER = "27655065477"
.\.venv\Scripts\python.exe -m flask --app app run --debug
```

For a hosted site, set `WHATSAPP_NUMBER` in the host's environment settings and restart the app. The footer, chat buttons and order redirects all use this setting.

## Customer requirements

Choose a package on the Order page to show the relevant questions. Answers are optional and saved in the order's notes in SQLite. For customers who start directly on WhatsApp, you can save these as quick replies:

- **CV:** What is your highest qualification or current course? Which roles are you applying for? What experience or skills should we highlight?
- **Website:** What does your business do? Which pages or features do you need? What colours or example websites do you like?
- **Flyer:** What are you promoting? What prices or dates should appear? Which colours or style do you like? Send any logo or photos you want to use.
- **Maintenance:** What is your website address or database platform? What needs changing or checking? When do you need it?

Use the order reference to match the chat with the saved order. Keep passwords and database credentials out of the intake.

### Set up a WhatsApp greeting

In WhatsApp Business on your phone, open **Tools → Greeting message** and enable it. Paste this greeting and select who should receive it:

> Hi! Thanks for messaging PHET-Digital. If you placed an order online, please send your order reference. Otherwise, tell me which service you need and I’ll help you get started.

### Set up WhatsApp quick replies

In WhatsApp Business on your phone, open **Tools → Quick replies → Add**. Paste one of the questions above as the message and save a shortcut such as `cv`, `website`, `flyer` or `maintenance`. In a customer chat, type `/`, choose the reply, edit it if needed and send.

## Prepare for hosting

Open /privacy locally and review the Privacy Policy before publishing. The app needs Python plus persistent storage for its instance folder so orders and testimonials survive a restart. The WhatsApp buttons open a normal chat with the business number. The app does not require a Meta developer account, API token or tunnel.

If you replace your local project files, keep your existing instance folder. It contains your orders and feedback database.

## Set up the private orders dashboard

In a second VS Code PowerShell terminal from the project folder, run once:

```powershell
.\.venv\Scripts\python.exe -m flask --app app admin setup
```

Save the generated password privately, restart Flask, then open http://127.0.0.1:5000/admin/. Sign in, select an order, and read the saved form. All orders use the existing SQLite database. Keep the `instance` folder private, including `admin-config.json` and `orders.sqlite3`.

For a hosted deployment, serve the app over HTTPS and set `PHET_ADMIN_HTTPS=1` so browsers only send the admin session cookie over HTTPS. The app and the setup command must use the same persistent instance folder. Run admin setup there if you have not yet configured the hosted login.

## Request and approve feedback in the admin dashboard

Open an order in **Admin → Orders** and click **Request feedback**. On your hosted site, click **Open WhatsApp message** and send the prepared text. Your customer opens the link, writes their feedback, and chooses a display name or Anonymous before giving permission to publish. On localhost, use **Open test feedback form** to try it on your computer.

Click **Review testimonials** on the Orders page, then **Approve** or **Reject**. Approved testimonials appear on the homepage. Set the optional `PHET_PUBLIC_URL` environment variable to your public HTTPS website address if your hosting setup uses an internal hostname or domain.

Reopening an admin feedback link uses the same invitation until the customer submits. The order page shows when feedback is ready for review or published. If you decline a review and need a revised one, use **Request new feedback**.

### Manage orders without the terminal

The Orders dashboard can search by reference, customer name or phone number and filter by status. Open an order to save its status or open a WhatsApp draft to follow up with the customer. Set **Deposit confirmed** only after you confirm payment yourself. Saving a status does not send a message or collect a payment.
