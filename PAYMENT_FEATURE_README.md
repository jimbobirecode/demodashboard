# Payment Feature Setup Guide

This guide will help you set up and use the new Stripe payment integration and Tour Operator features in the TeeMail Demo Dashboard.

## 🎯 Features

### 1. **Stripe Payment Links**
- Create secure payment links directly from the dashboard
- Automatically send payment requests via email
- Choose between deposit or full payment
- Track payment history for each booking

### 2. **Tour Operator Support**
- Mark bookings as "Tour Operator" customers
- Tour Operators automatically get 50% deposit requirement
- Regular customers get default 20% deposit requirement
- Deposit percentage is customizable per booking type

### 3. **Payment Tracking**
- Track payment status: Not Requested, Pending, Deposit Paid, Fully Paid, Failed
- View payment history directly in booking details
- Monitor total paid vs. total amount owed

---

## 📋 Prerequisites

1. **Stripe Account** - Sign up at [stripe.com](https://stripe.com)
2. **Stripe API Keys** - Get from your Stripe Dashboard
3. **SendGrid Account** - For sending payment request emails
4. **PostgreSQL Database** - Running instance with access

---

## 🚀 Installation Steps

### Step 1: Database Migration

Run the SQL migration to add payment tables and fields:

```bash
psql $DATABASE_URL -f add_payments_and_tour_operator.sql
```

This will:
- Create the `payments` table to track all payment transactions
- Add `is_tour_operator`, `payment_status`, `deposit_percentage`, and `total_paid` columns to the `bookings` table
- Set up proper indexes and triggers for automatic timestamp updates

**Verify the migration:**
```sql
-- Check if payments table exists
SELECT * FROM information_schema.tables WHERE table_name = 'payments';

-- Check if new columns exist in bookings table
SELECT column_name FROM information_schema.columns
WHERE table_name = 'bookings'
AND column_name IN ('is_tour_operator', 'payment_status', 'deposit_percentage', 'total_paid');
```

### Step 2: Install Python Dependencies

```bash
pip install -r requirements.txt
```

This will install the new `stripe==7.11.0` package along with other dependencies.

### Step 3: Configure Environment Variables

Add the following environment variables to your `.env` file or system environment:

```bash
# Stripe Configuration (REQUIRED for payments)
STRIPE_SECRET_KEY=sk_test_xxxxxxxxxxxxxxxxxxxxx
STRIPE_PUBLISHABLE_KEY=pk_test_xxxxxxxxxxxxxxxxxxxxx

# Deposit Configuration (OPTIONAL - defaults shown)
DEFAULT_DEPOSIT_PERCENTAGE=20  # Regular customers: 20% deposit

# SendGrid Configuration (already required for existing features)
SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxxxxxxx
FROM_EMAIL=noreply@teemail.com
FROM_NAME=TeeMail Demo

# Database (already configured)
DATABASE_URL=postgresql://user:password@localhost:5432/database
```

**How to get your Stripe keys:**
1. Log in to your [Stripe Dashboard](https://dashboard.stripe.com)
2. Go to **Developers** → **API Keys**
3. Copy your **Secret key** (starts with `sk_test_` or `sk_live_`)
4. Copy your **Publishable key** (starts with `pk_test_` or `pk_live_`)

**Important:**
- Use `sk_test_` keys for testing
- Use `sk_live_` keys for production (real payments)
- Never commit API keys to version control

### Step 4: Restart the Application

```bash
streamlit run dashboard.py
```

---

## 💳 How to Use the Payment Features

### **Mark a Booking as Tour Operator**

1. Navigate to **Bookings** page
2. Find the booking you want to modify
3. Click **View Full Details** to expand
4. In the **Quick Actions** panel (right side), toggle **"Tour Operator (50% deposit)"**
5. The deposit percentage will automatically change from 20% to 50%

### **Send a Payment Request**

1. Navigate to **Bookings** page
2. Find the booking and click **View Full Details**
3. In the **Quick Actions** panel, scroll to **💳 Payment Request**
4. Choose payment type:
   - **Deposit** - Charges the deposit percentage (20% or 50% for Tour Operators)
   - **Full Payment** - Charges the complete booking amount
5. Review the calculated amount
6. Click **📧 Send Payment Request**
7. The system will:
   - Create a secure Stripe payment link
   - Save the payment record to the database
   - Send a professional email to the guest with the payment link
   - Update the booking's payment status to "Pending"

### **Track Payment Status**

In the **Quick Actions** panel, you'll see:
- **Payment Status**: Current status (Not Requested, Pending, Deposit Paid, Fully Paid, Failed)
- **Paid Amount**: €X.XX / €Y.YY (amount paid vs. total)
- **Deposit**: Current deposit percentage
- **Payment History**: Last 3 payment requests with dates and amounts

---

## 📊 Payment Status Lifecycle

```
Not Requested → Pending → Deposit Paid or Fully Paid
                   ↓
                Failed (can retry)
```

- **Not Requested**: No payment link has been sent
- **Pending**: Payment link sent, awaiting customer payment
- **Deposit Paid**: Customer paid the deposit amount
- **Fully Paid**: Customer paid the full booking amount
- **Failed**: Payment attempt failed (can send new request)

---

## 🔧 Configuration Options

### Change Default Deposit Percentage

Edit the environment variable:
```bash
DEFAULT_DEPOSIT_PERCENTAGE=25  # Change from 20% to 25%
```

### Tour Operator Deposit Percentage

This is hardcoded to 50% in the dashboard. To change it, edit `dashboard.py`:

```python
TOUR_OPERATOR_DEPOSIT_PERCENTAGE = 50  # Change this value
```

### Customize Payment Success Redirect

After successful payment, customers are redirected to a URL. Change it in `dashboard.py`:

```python
# In create_stripe_payment_link function
after_completion={
    'type': 'redirect',
    'redirect': {
        'url': 'https://www.yourwebsite.com/payment-success'  # Change this
    }
}
```

---

## 📧 Email Template

The payment request email includes:
- Personalized greeting with guest name
- Booking details (ID, date, time, players)
- Payment amount with clear CTA button
- Stripe-powered secure payment link
- TeeMail branding

The email is automatically formatted in HTML with professional styling.

---

## 🛡️ Security Best Practices

1. **API Keys**:
   - Never commit API keys to Git
   - Use environment variables
   - Rotate keys periodically
   - Use test keys in development

2. **Payment Links**:
   - Stripe payment links are secure and PCI-compliant
   - Links expire after a certain period (configurable in Stripe)
   - All payment data is handled by Stripe (not stored in your database)

3. **Database**:
   - Payment records store references to Stripe objects (session IDs, payment intent IDs)
   - Actual card details never touch your database
   - Use SSL/TLS for database connections

---

## 🐛 Troubleshooting

### "Stripe not configured" Warning

**Problem**: STRIPE_SECRET_KEY environment variable is not set

**Solution**:
```bash
export STRIPE_SECRET_KEY=sk_test_xxxxxxxxxxxxx
```
Then restart the application.

### Email Not Sending

**Problem**: SendGrid API key not configured or invalid

**Solution**:
1. Verify SENDGRID_API_KEY is set correctly
2. Verify FROM_EMAIL is a verified sender in SendGrid
3. Check SendGrid dashboard for error logs

### Payment Link Creation Fails

**Problem**: Stripe API error

**Common causes**:
- Invalid API key
- Insufficient permissions on API key
- Network connectivity issues
- Invalid booking amount (must be > 0)

**Solution**:
1. Check Stripe Dashboard → Developers → API Keys
2. Ensure key has proper permissions
3. Check application logs for specific error message

### Database Error: Column Not Found

**Problem**: Database migration not run

**Solution**:
```bash
psql $DATABASE_URL -f add_payments_and_tour_operator.sql
```

---

## 📖 Database Schema Reference

### `payments` Table

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| payment_id | VARCHAR(100) | Unique payment identifier |
| booking_id | VARCHAR(50) | Foreign key to bookings |
| stripe_payment_link_id | VARCHAR(255) | Stripe payment link ID |
| stripe_checkout_session_id | VARCHAR(255) | Stripe checkout session ID |
| amount | DECIMAL(10, 2) | Payment amount |
| currency | VARCHAR(3) | Currency code (default: EUR) |
| payment_type | VARCHAR(20) | 'deposit' or 'full' |
| deposit_percentage | INTEGER | Deposit % (20, 50, etc.) |
| payment_status | VARCHAR(20) | Status (pending, paid, failed, etc.) |
| payment_link_url | TEXT | Full Stripe payment link URL |
| payment_link_sent_at | TIMESTAMP | When email was sent |
| payment_received_at | TIMESTAMP | When payment completed |
| created_at | TIMESTAMP | Record creation time |
| updated_at | TIMESTAMP | Last update time |
| created_by | VARCHAR(100) | Staff member who created |
| notes | TEXT | Additional notes |

### `bookings` Table (New Columns)

| Column | Type | Description |
|--------|------|-------------|
| is_tour_operator | BOOLEAN | Is this a tour operator booking? |
| payment_status | VARCHAR(20) | Current payment status |
| deposit_percentage | INTEGER | Required deposit percentage |
| total_paid | DECIMAL(10, 2) | Total amount paid so far |

---

## 🔄 Webhook Integration (Future Enhancement)

Currently, payment status updates are manual. For automatic updates when customers pay, you'll need to:

1. Set up a Stripe webhook endpoint
2. Listen for `checkout.session.completed` events
3. Update `payment_status` and `total_paid` in the database

Example webhook endpoint (not included in current version):
```python
@app.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')

    # Verify and process webhook
    # Update payment_status and total_paid
```

---

## 📞 Support

For issues or questions:
- Check the troubleshooting section above
- Review Stripe documentation: [stripe.com/docs](https://stripe.com/docs)
- Check SendGrid documentation: [sendgrid.com/docs](https://sendgrid.com/docs)

---

## ✅ Quick Checklist

Before going live with payments:

- [ ] Database migration completed
- [ ] Stripe API keys configured (use `sk_live_` for production)
- [ ] SendGrid configured and tested
- [ ] Test payment flow with test card (4242 4242 4242 4242)
- [ ] Verify emails are being sent
- [ ] Verify payment links are accessible
- [ ] Set proper success redirect URL
- [ ] Train staff on using payment features

---

**Last Updated**: 2026-01-01
**Version**: 1.0.0
