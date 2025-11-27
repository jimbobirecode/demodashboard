# Email Bot & Dashboard Integration Guide

This guide explains how to connect your email bot to the dashboard waitlist system.

## Architecture Overview

```
┌─────────────────┐     API Calls      ┌─────────────────┐
│                 │  ───────────────►  │                 │
│   Email Bot     │                    │   Waitlist API  │
│                 │  ◄───────────────  │   (api.py)      │
└─────────────────┘     Responses      └────────┬────────┘
                                                │
                                                │ PostgreSQL
                                                ▼
                                       ┌─────────────────┐
                                       │                 │
                                       │    Database     │
                                       │   (waitlist)    │
                                       │                 │
                                       └────────┬────────┘
                                                │
                                                │ Reads
                                                ▼
                                       ┌─────────────────┐
                                       │                 │
                                       │   Dashboard     │
                                       │  (Streamlit)    │
                                       │                 │
                                       └─────────────────┘
```

---

## Part 1: Email Bot Configuration

### Step 1: Set Up API Credentials

Add these environment variables to your email bot:

```bash
WAITLIST_API_URL=https://your-dashboard-domain.com/api
WAITLIST_API_KEY=your-secret-api-key-here
```

### Step 2: Detect When to Offer Waitlist

In your email bot, when a customer requests a tee time that's unavailable:

```python
# Pseudo-code for email bot logic

def process_booking_request(email_content):
    # Parse the booking request
    requested_date = extract_date(email_content)
    requested_time = extract_time(email_content)

    # Check availability with your booking system
    available = check_tee_time_availability(requested_date, requested_time)

    if not available:
        # Tee time not available - offer waitlist opt-in
        send_waitlist_offer_email(customer_email, requested_date, requested_time)
    else:
        # Process normal booking
        create_booking(...)
```

### Step 3: Send Waitlist Opt-In Email

When tee time is unavailable, send this type of email to the customer:

```
Subject: Tee Time Unavailable - Join Our Waitlist?

Dear [Customer Name],

Unfortunately, the tee time you requested for [Date] at [Time] is not currently available.

Would you like to be added to our waitlist? If a spot opens up, we'll notify you immediately.

Reply with "YES" to join the waitlist, or "NO" to decline.

Best regards,
The Island Golf Club
```

### Step 4: Handle Opt-In Response

When customer replies "YES", call the waitlist API:

```python
import requests

def add_customer_to_waitlist(customer_data):
    """
    Call this when customer opts in to the waitlist
    """
    api_url = os.getenv('WAITLIST_API_URL')
    api_key = os.getenv('WAITLIST_API_KEY')

    payload = {
        "guest_email": customer_data['email'],
        "guest_name": customer_data.get('name', ''),
        "requested_date": customer_data['date'],  # Format: "2024-03-15"
        "preferred_time": customer_data.get('time', 'Flexible'),
        "time_flexibility": customer_data.get('flexibility', 'Flexible'),
        "players": customer_data.get('players', 4),
        "golf_course": customer_data.get('course', 'The Island Golf Club'),
        "club": "island",  # Your club ID
        "notes": customer_data.get('notes', ''),
        "priority": 5,  # 1-10, higher = more priority
        "opt_in_confirmed": True,
        "original_booking_request": customer_data.get('original_email', '')
    }

    headers = {
        'Content-Type': 'application/json',
        'X-API-Key': api_key
    }

    response = requests.post(
        f"{api_url}/waitlist/add",
        json=payload,
        headers=headers
    )

    if response.status_code == 201:
        result = response.json()
        # Send confirmation email to customer
        send_waitlist_confirmation(
            customer_data['email'],
            result['waitlist_id'],
            customer_data['date']
        )
        return True, result['waitlist_id']
    elif response.status_code == 409:
        # Customer already on waitlist for this date
        return False, "Already on waitlist"
    else:
        return False, response.json().get('error', 'Unknown error')
```

### Step 5: Check Waitlist Status (Optional)

Before adding to waitlist, you can check if customer is already on it:

```python
def check_if_on_waitlist(email, date, club="island"):
    api_url = os.getenv('WAITLIST_API_URL')
    api_key = os.getenv('WAITLIST_API_KEY')

    response = requests.get(
        f"{api_url}/waitlist/check",
        params={
            'email': email,
            'date': date,
            'club': club
        },
        headers={'X-API-Key': api_key}
    )

    if response.status_code == 200:
        result = response.json()
        return result['on_waitlist'], result.get('entries', [])
    return False, []
```

---

## Part 2: Dashboard API Setup

### Step 1: Install Dependencies

Add to `requirements.txt`:

```
flask>=2.0.0
gunicorn>=20.0.0
```

### Step 2: Set Environment Variables

```bash
# Database connection (same as dashboard)
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# API security key (generate a strong random string)
WAITLIST_API_KEY=your-secret-key-here-make-it-long-and-random
```

### Step 3: Run the API Server

**Development:**
```bash
python api.py
```

**Production (with Gunicorn):**
```bash
gunicorn api:app --bind 0.0.0.0:5000 --workers 2
```

### Step 4: Deploy API Alongside Dashboard

If using Railway, Render, or Heroku, you can run both:

**Option A: Separate Services**
- Deploy `dashboard.py` as Streamlit app
- Deploy `api.py` as Flask app on different port

**Option B: Single Deployment with Procfile**
```
web: streamlit run dashboard.py --server.port=$PORT
api: gunicorn api:app --bind 0.0.0.0:5000
```

---

## Part 3: API Reference

### Base URL
```
https://your-domain.com/api
```

### Authentication
All endpoints require `X-API-Key` header:
```
X-API-Key: your-secret-api-key
```

### Endpoints

#### 1. Add to Waitlist
```
POST /api/waitlist/add
```

**Request Body:**
```json
{
    "guest_email": "customer@example.com",
    "guest_name": "John Doe",
    "requested_date": "2024-03-15",
    "preferred_time": "10:00 AM",
    "time_flexibility": "Flexible",
    "players": 4,
    "golf_course": "The Island Golf Club",
    "club": "island",
    "notes": "Celebrating birthday",
    "priority": 5,
    "opt_in_confirmed": true,
    "original_booking_request": "Full email content..."
}
```

**Response (201 Created):**
```json
{
    "success": true,
    "message": "Customer added to waitlist",
    "waitlist_id": "WL-20240315120000-1234",
    "created_at": "2024-03-15T12:00:00Z"
}
```

**Response (409 Conflict):**
```json
{
    "success": false,
    "message": "Customer already on waitlist for this date",
    "waitlist_id": "WL-20240315100000-1234",
    "status": "Waiting"
}
```

#### 2. Check Waitlist Status
```
GET /api/waitlist/check?email=customer@example.com&date=2024-03-15&club=island
```

**Response:**
```json
{
    "on_waitlist": true,
    "count": 1,
    "entries": [
        {
            "waitlist_id": "WL-20240315120000-1234",
            "guest_email": "customer@example.com",
            "requested_date": "2024-03-15",
            "status": "Waiting",
            "priority": 5
        }
    ]
}
```

#### 3. Update Waitlist Entry
```
PATCH /api/waitlist/update/{waitlist_id}
```

**Request Body:**
```json
{
    "status": "Notified",
    "notification_sent": true,
    "notes": "Notified via email on March 14"
}
```

#### 4. Get Matching Entries (When Slot Opens)
```
GET /api/waitlist/matches?date=2024-03-15&club=island&time=10:00
```

**Response:**
```json
{
    "available_date": "2024-03-15",
    "available_time": "10:00",
    "matches_found": 3,
    "matches": [
        {
            "waitlist_id": "WL-...",
            "guest_email": "high-priority@example.com",
            "priority": 8
        }
    ]
}
```

#### 5. Remove from Waitlist
```
DELETE /api/waitlist/remove/{waitlist_id}
```

---

## Part 4: Workflow Example

### Complete Flow: Customer Can't Get Tee Time

1. **Customer emails:** "I'd like to book a tee time for March 15th at 10am for 4 players"

2. **Email bot checks availability:** Not available

3. **Email bot sends opt-in email:**
   ```
   Sorry, that time isn't available. Reply YES to join our waitlist.
   ```

4. **Customer replies:** "YES"

5. **Email bot calls API:**
   ```python
   add_customer_to_waitlist({
       'email': 'customer@example.com',
       'name': 'John Doe',
       'date': '2024-03-15',
       'time': '10:00 AM',
       'players': 4,
       'flexibility': 'Flexible'
   })
   ```

6. **API adds to database** with `source: 'email_bot'`

7. **Dashboard shows entry** with "EMAIL OPT-IN" badge

8. **When slot opens:**
   - Staff sees waitlist in dashboard
   - Clicks "Notify Customer"
   - Or: Email bot calls `/api/waitlist/matches` to auto-notify

9. **Convert to booking:**
   - Staff clicks "Convert to Booking"
   - Customer gets confirmation

---

## Part 5: Testing

### Test the API

```bash
# Health check
curl http://localhost:5000/api/health

# Add to waitlist
curl -X POST http://localhost:5000/api/waitlist/add \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key" \
  -d '{
    "guest_email": "test@example.com",
    "requested_date": "2024-03-15",
    "club": "island",
    "opt_in_confirmed": true
  }'

# Check status
curl "http://localhost:5000/api/waitlist/check?email=test@example.com&club=island" \
  -H "X-API-Key: your-secret-key"
```

---

## Troubleshooting

### Common Issues

1. **401 Unauthorized**
   - Check `X-API-Key` header matches `WAITLIST_API_KEY` env var

2. **409 Conflict (Already on waitlist)**
   - Customer already has an active waitlist entry for that date

3. **Database connection errors**
   - Verify `DATABASE_URL` is set correctly
   - Ensure PostgreSQL is accessible from API server

4. **Entries not showing in dashboard**
   - Check `club` parameter matches the dashboard user's `customer_id`
   - Verify entry status is in the selected filter

### Need Help?

Check the API logs for detailed error messages, or test endpoints with curl/Postman first.
