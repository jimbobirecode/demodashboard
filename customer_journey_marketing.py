"""
CUSTOMER JOURNEY MARKETING LOGIC
Standalone module for pre-arrival and post-play email automation

This can be integrated into any codebase that uses:
- PostgreSQL database with bookings table
- SendGrid for email delivery
- Python 3.7+

REQUIREMENTS:
pip install sendgrid psycopg pandas

DATABASE SCHEMA REQUIREMENTS:
- Bookings table must have these columns:
  - booking_id (unique identifier)
  - guest_email
  - date (play date)
  - tee_time (or selected_tee_times, or note field with time)
  - golf_courses
  - players
  - status
  - club (if multi-club system)

- Optional tracking columns (add with migration):
  - pre_arrival_email_sent_at (TIMESTAMP)
  - post_play_email_sent_at (TIMESTAMP)
"""

import os
import re
import json
from datetime import datetime, timedelta
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import pandas as pd
import psycopg
from psycopg.rows import dict_row


# ============================================================================
# CONFIGURATION
# ============================================================================

class EmailConfig:
    """Email configuration - set these in your environment"""
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
    FROM_EMAIL = os.environ.get('FROM_EMAIL')
    FROM_NAME = os.environ.get('FROM_NAME', 'Streamsong Golf Resort')

    # SendGrid Template IDs
    TEMPLATE_PRE_ARRIVAL = os.environ.get('SENDGRID_TEMPLATE_PRE_ARRIVAL')
    TEMPLATE_POST_PLAY = os.environ.get('SENDGRID_TEMPLATE_POST_PLAY')

    # Database connection
    DATABASE_URL = os.environ.get('DATABASE_URL')

    # Marketing timing (days)
    PRE_ARRIVAL_DAYS = 3  # Send welcome email 3 days before play
    POST_PLAY_DAYS = 2    # Send thank you email 2 days after play


# ============================================================================
# HELPER FUNCTIONS - Tee Time Extraction
# ============================================================================

def extract_tee_time_from_note(note_content):
    """
    Extract tee time from email/note content

    Looks for patterns like:
    - Time: 12:20 PM
    - Tee Time: 3:45 PM
    """
    if not note_content or pd.isna(note_content):
        return None

    patterns = [
        r'Time:\s*(\d{1,2}:\d{2}\s*[AaPp][Mm])',
        r'time:\s*(\d{1,2}:\d{2}\s*[AaPp][Mm])',
        r'Tee\s+Time:\s*(\d{1,2}:\d{2}\s*[AaPp][Mm])',
    ]

    for pattern in patterns:
        match = re.search(pattern, str(note_content), re.IGNORECASE)
        if match:
            return match.group(1).strip().upper()

    return None


def extract_tee_time_from_selected_tee_times(selected_tee_times):
    """
    Extract tee time from selected_tee_times field

    Handles multiple formats:
    - JSON: {"time": "10:35 AM", "course": "Blue"}
    - Dict object
    - Go map: map[time:10:35 AM course:Blue]
    - Plain string: "10:35 AM"
    """
    if not selected_tee_times:
        return None

    # If it's already a dict, extract the 'time' key
    if isinstance(selected_tee_times, dict):
        return selected_tee_times.get('time')

    # If it's a string, try multiple parsing strategies
    if isinstance(selected_tee_times, str):
        # Strategy 1: Try parsing as JSON
        try:
            data = json.loads(selected_tee_times)
            if isinstance(data, dict) and 'time' in data:
                return data['time']
        except (json.JSONDecodeError, ValueError):
            pass

        # Strategy 2: Check if it's a Go map format (map[...time:10:35 AM...])
        map_time_match = re.search(r'time:(\d{1,2}:\d{2}\s*[AaPp][Mm])', selected_tee_times)
        if map_time_match:
            return map_time_match.group(1).strip()

        # Strategy 3: If it's already just the time string
        if re.match(r'\d{1,2}:\d{2}\s*[AaPp][Mm]', selected_tee_times):
            return selected_tee_times

    return None


def get_tee_time_from_booking(booking):
    """
    Get tee time from booking, trying multiple sources

    Priority:
    1. tee_time column (if populated)
    2. Extract from selected_tee_times JSON/dict
    3. Extract from note field
    4. Default to 'TBD'
    """
    # Try tee_time column first
    if booking.get('tee_time'):
        return booking['tee_time']

    # Try extracting from selected_tee_times
    if booking.get('selected_tee_times'):
        extracted = extract_tee_time_from_selected_tee_times(booking['selected_tee_times'])
        if extracted:
            return extracted

    # Try extracting from note field
    if booking.get('note'):
        extracted = extract_tee_time_from_note(booking['note'])
        if extracted:
            return extracted

    # Default
    return 'TBD'


# ============================================================================
# DATABASE FUNCTIONS
# ============================================================================

def get_db_connection():
    """Get database connection"""
    return psycopg.connect(EmailConfig.DATABASE_URL)


def get_upcoming_bookings(days_ahead=None, club_filter=None):
    """
    Get bookings that need pre-arrival emails

    Args:
        days_ahead: Number of days ahead to look (default: PRE_ARRIVAL_DAYS)
        club_filter: Filter by club name (e.g., 'streamsong')

    Returns:
        List of booking dicts
    """
    if days_ahead is None:
        days_ahead = EmailConfig.PRE_ARRIVAL_DAYS

    target_date = (datetime.now() + timedelta(days=days_ahead)).date()

    conn = get_db_connection()
    cursor = conn.cursor(row_factory=dict_row)

    # Build WHERE clause
    where_conditions = ["status = 'Confirmed'", "date = %s"]
    params = [target_date]

    if club_filter:
        where_conditions.append("club = %s")
        params.append(club_filter)

    where_clause = " AND ".join(where_conditions)

    # Check if email tracking columns exist
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'bookings'
        AND column_name = 'pre_arrival_email_sent_at'
    """)
    has_tracking = cursor.fetchone() is not None

    # Build query
    query = f"""
        SELECT
            id,
            booking_id,
            guest_email,
            guest_name,
            date as play_date,
            tee_time,
            selected_tee_times,
            note,
            players,
            total,
            golf_courses,
            hotel_required,
            hotel_checkin,
            hotel_checkout,
            {('pre_arrival_email_sent_at' if has_tracking else 'NULL as pre_arrival_email_sent_at')}
        FROM bookings
        WHERE {where_clause}
        ORDER BY date, tee_time
    """

    cursor.execute(query, params)
    bookings = cursor.fetchall()
    cursor.close()
    conn.close()

    # Filter out already sent (if tracking exists)
    if has_tracking:
        bookings = [b for b in bookings if not b.get('pre_arrival_email_sent_at')]

    return bookings


def get_recent_bookings(days_ago=None, club_filter=None):
    """
    Get bookings that need post-play emails

    Args:
        days_ago: Number of days ago to look (default: POST_PLAY_DAYS)
        club_filter: Filter by club name (e.g., 'streamsong')

    Returns:
        List of booking dicts
    """
    if days_ago is None:
        days_ago = EmailConfig.POST_PLAY_DAYS

    target_date = (datetime.now() - timedelta(days=days_ago)).date()

    conn = get_db_connection()
    cursor = conn.cursor(row_factory=dict_row)

    # Build WHERE clause
    where_conditions = ["status = 'Confirmed'", "date = %s"]
    params = [target_date]

    if club_filter:
        where_conditions.append("club = %s")
        params.append(club_filter)

    where_clause = " AND ".join(where_conditions)

    # Check if email tracking columns exist
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'bookings'
        AND column_name = 'post_play_email_sent_at'
    """)
    has_tracking = cursor.fetchone() is not None

    # Build query
    query = f"""
        SELECT
            id,
            booking_id,
            guest_email,
            guest_name,
            date as play_date,
            tee_time,
            selected_tee_times,
            note,
            players,
            total,
            golf_courses,
            {('post_play_email_sent_at' if has_tracking else 'NULL as post_play_email_sent_at')}
        FROM bookings
        WHERE {where_clause}
        ORDER BY date DESC
    """

    cursor.execute(query, params)
    bookings = cursor.fetchall()
    cursor.close()
    conn.close()

    # Filter out already sent (if tracking exists)
    if has_tracking:
        bookings = [b for b in bookings if not b.get('post_play_email_sent_at')]

    return bookings


def mark_email_sent(booking_id, email_type):
    """
    Mark email as sent in database

    Args:
        booking_id: Booking ID
        email_type: 'pre_arrival' or 'post_play'
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    column_map = {
        'pre_arrival': 'pre_arrival_email_sent_at',
        'post_play': 'post_play_email_sent_at'
    }

    column = column_map.get(email_type)
    if not column:
        raise ValueError(f"Invalid email_type: {email_type}")

    # Check if column exists
    cursor.execute(f"""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'bookings'
        AND column_name = %s
    """, (column,))

    if cursor.fetchone():
        cursor.execute(f"""
            UPDATE bookings
            SET {column} = CURRENT_TIMESTAMP
            WHERE booking_id = %s
        """, (booking_id,))
        conn.commit()

    cursor.close()
    conn.close()


# ============================================================================
# EMAIL SENDING FUNCTIONS
# ============================================================================

def send_pre_arrival_email(booking):
    """
    Send pre-arrival welcome email

    Args:
        booking: Booking dict with all required fields

    Returns:
        (success: bool, message: str)
    """
    try:
        # Validate configuration
        if not EmailConfig.SENDGRID_API_KEY or not EmailConfig.FROM_EMAIL or not EmailConfig.TEMPLATE_PRE_ARRIVAL:
            return False, "SendGrid not configured"

        # Validate required fields
        if not booking.get('booking_id'):
            return False, "Missing booking_id"
        if not booking.get('guest_email'):
            return False, "Missing guest_email"
        if not booking.get('play_date'):
            return False, "Missing play_date"

        # Get guest name
        guest_name = booking.get('guest_name') or booking['guest_email'].split('@')[0].title()

        # Format play date
        play_date = booking['play_date']
        if hasattr(play_date, 'strftime'):
            formatted_date = play_date.strftime('%A, %B %d, %Y')
        else:
            formatted_date = str(play_date)

        # Get tee time from multiple sources
        tee_time_value = get_tee_time_from_booking(booking)

        # Prepare email data
        dynamic_data = {
            'guest_name': guest_name,
            'booking_date': formatted_date,
            'course_name': booking.get('golf_courses') or 'Golf Resort',
            'tee_time': tee_time_value,
            'player_count': str(booking.get('players', 0)),
            'booking_reference': booking['booking_id'],
            'current_year': str(datetime.now().year),
            'total': f"${booking.get('total', 0):.2f}" if booking.get('total') else '$0.00',
        }

        # Send email via SendGrid
        message = Mail(
            from_email=(EmailConfig.FROM_EMAIL, EmailConfig.FROM_NAME),
            to_emails=booking['guest_email']
        )
        message.template_id = EmailConfig.TEMPLATE_PRE_ARRIVAL
        message.dynamic_template_data = dynamic_data

        sg = SendGridAPIClient(EmailConfig.SENDGRID_API_KEY)
        response = sg.send(message)

        if response.status_code in [200, 202]:
            # Mark as sent
            mark_email_sent(booking['booking_id'], 'pre_arrival')
            return True, f"Pre-arrival email sent to {booking['guest_email']}"
        else:
            return False, f"SendGrid error: {response.status_code}"

    except Exception as e:
        return False, f"Error: {str(e)}"


def send_post_play_email(booking):
    """
    Send post-play thank you email

    Args:
        booking: Booking dict with all required fields

    Returns:
        (success: bool, message: str)
    """
    try:
        # Validate configuration
        if not EmailConfig.SENDGRID_API_KEY or not EmailConfig.FROM_EMAIL or not EmailConfig.TEMPLATE_POST_PLAY:
            return False, "SendGrid not configured"

        # Validate required fields
        if not booking.get('booking_id'):
            return False, "Missing booking_id"
        if not booking.get('guest_email'):
            return False, "Missing guest_email"
        if not booking.get('play_date'):
            return False, "Missing play_date"

        # Get guest name
        guest_name = booking.get('guest_name') or booking['guest_email'].split('@')[0].title()

        # Format play date
        play_date = booking['play_date']
        if hasattr(play_date, 'strftime'):
            formatted_date = play_date.strftime('%A, %B %d, %Y')
        else:
            formatted_date = str(play_date)

        # Get tee time from multiple sources
        tee_time_value = get_tee_time_from_booking(booking)

        # Prepare email data
        dynamic_data = {
            'guest_name': guest_name,
            'booking_date': formatted_date,
            'course_name': booking.get('golf_courses') or 'Golf Resort',
            'tee_time': tee_time_value,
            'player_count': str(booking.get('players', 0)),
            'booking_reference': booking['booking_id'],
            'current_year': str(datetime.now().year),
            'total': f"${booking.get('total', 0):.2f}" if booking.get('total') else '$0.00',
        }

        # Send email via SendGrid
        message = Mail(
            from_email=(EmailConfig.FROM_EMAIL, EmailConfig.FROM_NAME),
            to_emails=booking['guest_email']
        )
        message.template_id = EmailConfig.TEMPLATE_POST_PLAY
        message.dynamic_template_data = dynamic_data

        sg = SendGridAPIClient(EmailConfig.SENDGRID_API_KEY)
        response = sg.send(message)

        if response.status_code in [200, 202]:
            # Mark as sent
            mark_email_sent(booking['booking_id'], 'post_play')
            return True, f"Post-play email sent to {booking['guest_email']}"
        else:
            return False, f"SendGrid error: {response.status_code}"

    except Exception as e:
        return False, f"Error: {str(e)}"


# ============================================================================
# BATCH PROCESSING
# ============================================================================

def process_pre_arrival_emails(club_filter=None, dry_run=False):
    """
    Process all pending pre-arrival emails

    Args:
        club_filter: Filter by club name
        dry_run: If True, only show what would be sent

    Returns:
        (sent_count: int, failed_count: int, results: list)
    """
    bookings = get_upcoming_bookings(club_filter=club_filter)

    sent_count = 0
    failed_count = 0
    results = []

    for booking in bookings:
        if dry_run:
            results.append({
                'booking_id': booking['booking_id'],
                'email': booking['guest_email'],
                'status': 'would_send'
            })
            continue

        success, message = send_pre_arrival_email(booking)

        if success:
            sent_count += 1
        else:
            failed_count += 1

        results.append({
            'booking_id': booking['booking_id'],
            'email': booking['guest_email'],
            'status': 'sent' if success else 'failed',
            'message': message
        })

    return sent_count, failed_count, results


def process_post_play_emails(club_filter=None, dry_run=False):
    """
    Process all pending post-play emails

    Args:
        club_filter: Filter by club name
        dry_run: If True, only show what would be sent

    Returns:
        (sent_count: int, failed_count: int, results: list)
    """
    bookings = get_recent_bookings(club_filter=club_filter)

    sent_count = 0
    failed_count = 0
    results = []

    for booking in bookings:
        if dry_run:
            results.append({
                'booking_id': booking['booking_id'],
                'email': booking['guest_email'],
                'status': 'would_send'
            })
            continue

        success, message = send_post_play_email(booking)

        if success:
            sent_count += 1
        else:
            failed_count += 1

        results.append({
            'booking_id': booking['booking_id'],
            'email': booking['guest_email'],
            'status': 'sent' if success else 'failed',
            'message': message
        })

    return sent_count, failed_count, results


# ============================================================================
# COMMAND-LINE INTERFACE (Optional)
# ============================================================================

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("CUSTOMER JOURNEY EMAIL AUTOMATION")
    print("=" * 60)

    if len(sys.argv) < 2:
        print("\nUsage:")
        print("  python customer_journey_marketing.py pre-arrival [--club=streamsong] [--dry-run]")
        print("  python customer_journey_marketing.py post-play [--club=streamsong] [--dry-run]")
        print("  python customer_journey_marketing.py both [--club=streamsong] [--dry-run]")
        sys.exit(1)

    email_type = sys.argv[1]
    club_filter = None
    dry_run = '--dry-run' in sys.argv

    # Parse club filter
    for arg in sys.argv:
        if arg.startswith('--club='):
            club_filter = arg.split('=')[1]

    if dry_run:
        print("\n🔍 DRY RUN MODE - No emails will be sent\n")

    if email_type in ['pre-arrival', 'both']:
        print("\n📧 Processing Pre-Arrival Emails...")
        sent, failed, results = process_pre_arrival_emails(club_filter=club_filter, dry_run=dry_run)
        print(f"  ✅ Sent: {sent}")
        print(f"  ❌ Failed: {failed}")
        for r in results:
            status_icon = "✅" if r['status'] == 'sent' else "⚠️" if r['status'] == 'would_send' else "❌"
            print(f"  {status_icon} {r['booking_id']}: {r['email']} - {r.get('message', r['status'])}")

    if email_type in ['post-play', 'both']:
        print("\n📧 Processing Post-Play Emails...")
        sent, failed, results = process_post_play_emails(club_filter=club_filter, dry_run=dry_run)
        print(f"  ✅ Sent: {sent}")
        print(f"  ❌ Failed: {failed}")
        for r in results:
            status_icon = "✅" if r['status'] == 'sent' else "⚠️" if r['status'] == 'would_send' else "❌"
            print(f"  {status_icon} {r['booking_id']}: {r['email']} - {r.get('message', r['status'])}")

    print("\n" + "=" * 60)
    print("✅ Processing Complete")
    print("=" * 60)
