import streamlit as st
import pandas as pd
import os
import bcrypt
import psycopg
from psycopg.rows import dict_row
from datetime import datetime, timedelta
from io import BytesIO
import html
import re
import json
import requests
import stripe
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# ========================================
# DATABASE CONNECTION
# ========================================
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    """Get database connection"""
    return psycopg.connect(DATABASE_URL)

# ========================================
# STRIPE CONFIGURATION
# ========================================
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
DEFAULT_DEPOSIT_PERCENTAGE = int(os.getenv("DEFAULT_DEPOSIT_PERCENTAGE", "20"))
TOUR_OPERATOR_DEPOSIT_PERCENTAGE = 50

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

def create_stripe_payment_link(booking_id: str, amount: float, payment_type: str, deposit_percentage: int, guest_email: str, guest_name: str = None):
    """
    Create a Stripe payment link for a booking

    Args:
        booking_id: The booking ID
        amount: The amount to charge
        payment_type: 'deposit' or 'full'
        deposit_percentage: The deposit percentage (e.g., 20, 50)
        guest_email: Customer email
        guest_name: Customer name (optional)

    Returns:
        dict with payment_link_url, payment_id, and stripe_payment_link_id
    """
    if not STRIPE_SECRET_KEY:
        raise ValueError("STRIPE_SECRET_KEY is not set. Please configure Stripe API key in environment variables.")

    try:
        # Create a product for this booking
        product_name = f"Golf Booking {payment_type.capitalize()}"
        if payment_type == "deposit":
            product_name += f" ({deposit_percentage}%)"
        product_name += f" - {booking_id}"

        # Create Stripe payment link
        payment_link = stripe.PaymentLink.create(
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {
                        'name': product_name,
                        'description': f'Booking ID: {booking_id}'
                    },
                    'unit_amount': int(amount * 100),  # Convert to cents
                },
                'quantity': 1,
            }],
            after_completion={
                'type': 'redirect',
                'redirect': {
                    'url': 'https://www.teemail.com/payment-success'
                }
            },
            metadata={
                'booking_id': booking_id,
                'payment_type': payment_type,
                'deposit_percentage': str(deposit_percentage)
            },
            customer_creation='always',
            billing_address_collection='auto',
            phone_number_collection={'enabled': True}
        )

        # Generate unique payment ID
        payment_id = f"PAY-{datetime.now().strftime('%Y%m%d%H%M%S')}-{booking_id}"

        return {
            'payment_link_url': payment_link.url,
            'payment_id': payment_id,
            'stripe_payment_link_id': payment_link.id
        }
    except Exception as e:
        raise Exception(f"Failed to create Stripe payment link: {str(e)}")

def save_payment_record(booking_id: str, payment_id: str, amount: float, payment_type: str,
                       deposit_percentage: int, payment_link_url: str, stripe_payment_link_id: str,
                       created_by: str):
    """Save payment record to database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO payments (
                payment_id, booking_id, amount, payment_type, deposit_percentage,
                payment_link_url, stripe_payment_link_id, payment_status,
                payment_link_sent_at, created_by, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, NOW())
        """, (
            payment_id, booking_id, amount, payment_type, deposit_percentage,
            payment_link_url, stripe_payment_link_id, 'pending', created_by
        ))

        # Update booking payment status
        cursor.execute("""
            UPDATE bookings
            SET payment_status = %s
            WHERE booking_id = %s
        """, ('pending', booking_id))

        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving payment record: {e}")
        return False

def get_booking_payments(booking_id: str):
    """Get all payment records for a booking"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)

        cursor.execute("""
            SELECT * FROM payments
            WHERE booking_id = %s
            ORDER BY created_at DESC
        """, (booking_id,))

        payments = cursor.fetchall()
        cursor.close()
        conn.close()
        return payments
    except Exception as e:
        print(f"Error fetching payments: {e}")
        return []

def update_tour_operator_status(booking_id: str, is_tour_operator: bool):
    """Update tour operator status for a booking"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Set deposit percentage based on tour operator status
        deposit_percentage = TOUR_OPERATOR_DEPOSIT_PERCENTAGE if is_tour_operator else DEFAULT_DEPOSIT_PERCENTAGE

        cursor.execute("""
            UPDATE bookings
            SET is_tour_operator = %s, deposit_percentage = %s
            WHERE booking_id = %s
        """, (is_tour_operator, deposit_percentage, booking_id))

        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error updating tour operator status: {e}")
        return False

def get_club_display_name(club_id: str) -> str:
    """
    Get the proper display name for a golf club based on its ID.
    Maps internal club IDs to full display names.
    """
    club_mapping = {
        # New TeeMail identifiers
        'teemail': 'TeeMail Demo',
        'teemailclub': 'TeeMail Demo',
        'teemail-demo': 'TeeMail Demo',
        'teemail_demo': 'TeeMail Demo',
        # Legacy Island identifiers (backward compatibility until DB migration)
        'island': 'TeeMail Demo',
        'islandgolfclub': 'TeeMail Demo',
        'island-golf-club': 'TeeMail Demo',
        'island_golf_club': 'TeeMail Demo',
    }

    # Try to find mapping (case insensitive, strip whitespace)
    club_id_clean = club_id.strip().lower() if club_id else ''
    if club_id_clean in club_mapping:
        return club_mapping[club_id_clean]

    # Default: always return TeeMail Demo
    return 'TeeMail Demo'

def get_club_color(club_id: str) -> str:
    """
    Get the brand color for a specific golf club.
    Returns hex color code for club branding.
    """
    club_colors = {
        # New TeeMail identifiers
        'teemail': '#10b981',  # TeeMail Demo Emerald Green
        'teemailclub': '#10b981',
        'teemail-demo': '#10b981',
        'teemail_demo': '#10b981',
        # Legacy Island identifiers (backward compatibility)
        'island': '#10b981',
        'islandgolfclub': '#10b981',
        'island-golf-club': '#10b981',
        'island_golf_club': '#10b981',
    }

    club_id_clean = club_id.strip().lower() if club_id else ''
    return club_colors.get(club_id_clean, '#10b981')  # Default Emerald Green

def get_club_info(club_id: str) -> dict:
    """
    Get additional information for a specific golf club.
    Returns dict with club details like contact info, location, etc.
    """
    club_info = {
        # New TeeMail identifiers
        'teemail': {
            'phone': '(555) 000-MAIL',
            'email': 'demo@teemail.com',
            'location': 'TeeMail Demo Platform',
            'website': 'www.teemail.com'
        },
        'teemailclub': {
            'phone': '(555) 000-MAIL',
            'email': 'demo@teemail.com',
            'location': 'TeeMail Demo Platform',
            'website': 'www.teemail.com'
        },
        'teemail-demo': {
            'phone': '(555) 000-MAIL',
            'email': 'demo@teemail.com',
            'location': 'TeeMail Demo Platform',
            'website': 'www.teemail.com'
        },
        'teemail_demo': {
            'phone': '(555) 000-MAIL',
            'email': 'demo@teemail.com',
            'location': 'TeeMail Demo Platform',
            'website': 'www.teemail.com'
        },
        # Legacy Island identifiers (backward compatibility)
        'island': {
            'phone': '(555) 000-MAIL',
            'email': 'demo@teemail.com',
            'location': 'TeeMail Demo Platform',
            'website': 'www.teemail.com'
        },
        'islandgolfclub': {
            'phone': '(555) 000-MAIL',
            'email': 'demo@teemail.com',
            'location': 'TeeMail Demo Platform',
            'website': 'www.teemail.com'
        },
        'island-golf-club': {
            'phone': '(555) 000-MAIL',
            'email': 'demo@teemail.com',
            'location': 'TeeMail Demo Platform',
            'website': 'www.teemail.com'
        },
        'island_golf_club': {
            'phone': '(555) 000-MAIL',
            'email': 'demo@teemail.com',
            'location': 'TeeMail Demo Platform',
            'website': 'www.teemail.com'
        },
    }

    club_id_clean = club_id.strip().lower() if club_id else ''
    return club_info.get(club_id_clean, {
        'phone': 'N/A',
        'email': 'N/A',
        'location': 'N/A',
        'website': 'N/A'
    })

def extract_tee_time_from_note(note_content):
    """
    Extract tee time from email content.
    Looks for patterns like:
    - Time: 12:20 PM
    - Time: 10:30 AM
    - Tee Time: 3:45 PM
    """
    if not note_content or pd.isna(note_content):
        return None

    # Pattern to match "Time: HH:MM AM/PM"
    patterns = [
        r'Time:\s*(\d{1,2}:\d{2}\s*[AaPp][Mm])',  # Time: 12:20 PM
        r'time:\s*(\d{1,2}:\d{2}\s*[AaPp][Mm])',  # time: 12:20 pm (case insensitive)
        r'Tee\s+Time:\s*(\d{1,2}:\d{2}\s*[AaPp][Mm])',  # Tee Time: 12:20 PM
    ]

    for pattern in patterns:
        match = re.search(pattern, str(note_content), re.IGNORECASE)
        if match:
            tee_time = match.group(1).strip()
            # Normalize to uppercase (12:20 PM)
            return tee_time.upper()

    return None


def clean_email_address(email):
    """Remove mailto: prefix and clean email address"""
    if not email:
        return None
    email = str(email).strip()
    # Remove mailto: prefix if present
    if email.lower().startswith('mailto:'):
        email = email[7:]
    return email.strip()


# ============================================================================
# EMAIL AUTOMATION - Configuration and Helper Functions
# ============================================================================

class EmailConfig:
    """Email automation configuration"""
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
    FROM_EMAIL = os.environ.get('FROM_EMAIL')
    FROM_NAME = os.environ.get('FROM_NAME', 'TeeMail Demo')
    TEMPLATE_PRE_ARRIVAL = os.environ.get('SENDGRID_TEMPLATE_PRE_ARRIVAL')
    TEMPLATE_POST_PLAY = os.environ.get('SENDGRID_TEMPLATE_POST_PLAY')
    PRE_ARRIVAL_DAYS = 3
    POST_PLAY_DAYS = 2


def extract_tee_time_from_selected_tee_times(selected_tee_times):
    """Extract tee time from selected_tee_times field"""
    if not selected_tee_times:
        return None

    if isinstance(selected_tee_times, dict):
        return selected_tee_times.get('time')

    if isinstance(selected_tee_times, str):
        try:
            data = json.loads(selected_tee_times)
            if isinstance(data, dict) and 'time' in data:
                return data['time']
        except (json.JSONDecodeError, ValueError):
            pass

        map_time_match = re.search(r'time:(\d{1,2}:\d{2}\s*[AaPp][Mm])', selected_tee_times)
        if map_time_match:
            return map_time_match.group(1).strip()

        if re.match(r'\d{1,2}:\d{2}\s*[AaPp][Mm]', selected_tee_times):
            return selected_tee_times

    return None


def get_tee_time_from_booking(booking):
    """Get tee time from booking, trying multiple sources"""
    if booking.get('tee_time'):
        return booking['tee_time']

    if booking.get('selected_tee_times'):
        extracted = extract_tee_time_from_selected_tee_times(booking['selected_tee_times'])
        if extracted:
            return extracted

    if booking.get('note'):
        extracted = extract_tee_time_from_note(booking['note'])
        if extracted:
            return extracted

    return 'TBD'


def get_upcoming_bookings_for_email(days_ahead=None, club_filter=None):
    """Get bookings that need pre-arrival emails - now works regardless of date"""
    conn = get_db_connection()
    cursor = conn.cursor(row_factory=dict_row)

    # More flexible status filter - accept multiple confirmation statuses
    # Removed date restriction to allow sending emails regardless of play date
    where_conditions = ["status IN ('Confirmed', 'Booked', 'Requested', 'Inquiry')"]
    params = []

    if club_filter:
        where_conditions.append("(club = %s OR club IS NULL OR club = '')")
        params.append(club_filter)

    where_clause = " AND ".join(where_conditions)

    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'bookings'
        AND column_name = 'pre_arrival_email_sent_at'
    """)
    has_tracking = cursor.fetchone() is not None

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

    if has_tracking:
        bookings = [b for b in bookings if not b.get('pre_arrival_email_sent_at')]

    return bookings


def get_recent_bookings_for_email(days_ago=None, club_filter=None):
    """Get bookings that need post-play emails - now works regardless of date"""
    conn = get_db_connection()
    cursor = conn.cursor(row_factory=dict_row)

    # More flexible status filter - accept multiple confirmation statuses
    # Removed date restriction to allow sending emails regardless of play date
    where_conditions = ["status IN ('Confirmed', 'Booked', 'Requested', 'Inquiry')"]
    params = []

    if club_filter:
        where_conditions.append("(club = %s OR club IS NULL OR club = '')")
        params.append(club_filter)

    where_clause = " AND ".join(where_conditions)

    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'bookings'
        AND column_name = 'post_play_email_sent_at'
    """)
    has_tracking = cursor.fetchone() is not None

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

    if has_tracking:
        bookings = [b for b in bookings if not b.get('post_play_email_sent_at')]

    return bookings


def mark_email_sent(booking_id, email_type):
    """Mark email as sent in database"""
    conn = get_db_connection()
    cursor = conn.cursor()

    column_map = {
        'pre_arrival': 'pre_arrival_email_sent_at',
        'post_play': 'post_play_email_sent_at'
    }

    column = column_map.get(email_type)
    if not column:
        return

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


def send_pre_arrival_email(booking):
    """Send pre-arrival welcome email"""
    try:
        if not EmailConfig.SENDGRID_API_KEY or not EmailConfig.FROM_EMAIL or not EmailConfig.TEMPLATE_PRE_ARRIVAL:
            return False, "SendGrid not configured"

        if not booking.get('booking_id') or not booking.get('guest_email') or not booking.get('play_date'):
            return False, "Missing required booking fields"

        # Clean email address (remove mailto: prefix if present)
        guest_email = clean_email_address(booking['guest_email'])
        if not guest_email:
            return False, "Invalid email address"

        guest_name = booking.get('guest_name') or guest_email.split('@')[0].title()

        play_date = booking['play_date']
        if hasattr(play_date, 'strftime'):
            formatted_date = play_date.strftime('%A, %B %d, %Y')
        else:
            formatted_date = str(play_date)

        tee_time_value = get_tee_time_from_booking(booking)

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

        message = Mail(
            from_email=(EmailConfig.FROM_EMAIL, EmailConfig.FROM_NAME),
            to_emails=guest_email
        )
        message.template_id = EmailConfig.TEMPLATE_PRE_ARRIVAL
        message.dynamic_template_data = dynamic_data

        sg = SendGridAPIClient(EmailConfig.SENDGRID_API_KEY)
        response = sg.send(message)

        if response.status_code in [200, 202]:
            mark_email_sent(booking['booking_id'], 'pre_arrival')
            return True, f"Pre-arrival email sent to {guest_email}"
        else:
            return False, f"SendGrid error: {response.status_code}"

    except Exception as e:
        return False, f"Error: {str(e)}"


def send_post_play_email(booking):
    """Send post-play thank you email"""
    try:
        if not EmailConfig.SENDGRID_API_KEY or not EmailConfig.FROM_EMAIL or not EmailConfig.TEMPLATE_POST_PLAY:
            return False, "SendGrid not configured"

        if not booking.get('booking_id') or not booking.get('guest_email') or not booking.get('play_date'):
            return False, "Missing required booking fields"

        # Clean email address (remove mailto: prefix if present)
        guest_email = clean_email_address(booking['guest_email'])
        if not guest_email:
            return False, "Invalid email address"

        guest_name = booking.get('guest_name') or guest_email.split('@')[0].title()

        play_date = booking['play_date']
        if hasattr(play_date, 'strftime'):
            formatted_date = play_date.strftime('%A, %B %d, %Y')
        else:
            formatted_date = str(play_date)

        tee_time_value = get_tee_time_from_booking(booking)

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

        message = Mail(
            from_email=(EmailConfig.FROM_EMAIL, EmailConfig.FROM_NAME),
            to_emails=guest_email
        )
        message.template_id = EmailConfig.TEMPLATE_POST_PLAY
        message.dynamic_template_data = dynamic_data

        sg = SendGridAPIClient(EmailConfig.SENDGRID_API_KEY)
        response = sg.send(message)

        if response.status_code in [200, 202]:
            mark_email_sent(booking['booking_id'], 'post_play')
            return True, f"Post-play email sent to {guest_email}"
        else:
            return False, f"SendGrid error: {response.status_code}"

    except Exception as e:
        return False, f"Error: {str(e)}"


def send_payment_request_email(booking, payment_link_url: str, amount: float, payment_type: str):
    """Send payment request email with Stripe payment link"""
    try:
        if not EmailConfig.SENDGRID_API_KEY or not EmailConfig.FROM_EMAIL:
            return False, "SendGrid not configured"

        if not booking.get('booking_id') or not booking.get('guest_email'):
            return False, "Missing required booking fields"

        # Clean email address
        guest_email = clean_email_address(booking['guest_email'])
        if not guest_email:
            return False, "Invalid email address"

        # Extract guest name
        guest_name = booking.get('guest_name', 'Guest')

        # Format tee date
        tee_date = booking.get('date')
        if tee_date and not pd.isna(tee_date):
            formatted_date = tee_date.strftime('%B %d, %Y')
        else:
            formatted_date = 'TBD'

        # Extract tee time
        tee_time_value = extract_tee_time_from_selected_tee_times(booking.get('selected_tee_times'))
        if not tee_time_value or tee_time_value == 'Not specified':
            tee_time_value = booking.get('tee_time', 'TBD')

        # Prepare email content
        payment_type_text = "Deposit" if payment_type == "deposit" else "Full Payment"

        # Build HTML email content
        email_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background-color: white; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); padding: 30px; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 28px;">Payment Request</h1>
                    <p style="color: white; margin: 10px 0 0 0; font-size: 16px;">TeeMail Demo</p>
                </div>

                <div style="padding: 30px;">
                    <p style="font-size: 16px; color: #333;">Dear {guest_name},</p>

                    <p style="font-size: 16px; color: #333; line-height: 1.6;">
                        Thank you for your booking! We're excited to welcome you to our golf course.
                    </p>

                    <p style="font-size: 16px; color: #333; line-height: 1.6;">
                        To secure your reservation, please complete your <strong>{payment_type_text}</strong> payment using the secure link below:
                    </p>

                    <div style="background-color: #f8f9fa; border-left: 4px solid #10b981; padding: 20px; margin: 20px 0;">
                        <p style="margin: 0 0 10px 0; color: #666; font-size: 14px;"><strong>Booking Details:</strong></p>
                        <p style="margin: 5px 0; color: #333;"><strong>Booking ID:</strong> {booking['booking_id']}</p>
                        <p style="margin: 5px 0; color: #333;"><strong>Tee Date:</strong> {formatted_date}</p>
                        <p style="margin: 5px 0; color: #333;"><strong>Tee Time:</strong> {tee_time_value}</p>
                        <p style="margin: 5px 0; color: #333;"><strong>Players:</strong> {booking.get('players', 0)}</p>
                        <p style="margin: 5px 0; color: #333;"><strong>Amount Due:</strong> €{amount:.2f}</p>
                    </div>

                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{payment_link_url}" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; padding: 15px 40px; text-decoration: none; border-radius: 8px; font-size: 16px; font-weight: bold; display: inline-block;">
                            Pay Now - €{amount:.2f}
                        </a>
                    </div>

                    <p style="font-size: 14px; color: #666; line-height: 1.6;">
                        This payment link is secure and powered by Stripe. You can pay with any major credit or debit card.
                    </p>

                    <p style="font-size: 14px; color: #666; line-height: 1.6;">
                        If you have any questions, please don't hesitate to contact us.
                    </p>

                    <p style="font-size: 16px; color: #333; margin-top: 30px;">
                        We look forward to seeing you!<br>
                        <strong>The TeeMail Demo Team</strong>
                    </p>
                </div>

                <div style="background-color: #f8f9fa; padding: 20px; text-align: center; border-top: 1px solid #e9ecef;">
                    <p style="margin: 0; color: #666; font-size: 12px;">
                        © {datetime.now().year} TeeMail Demo. All rights reserved.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """

        message = Mail(
            from_email=(EmailConfig.FROM_EMAIL, EmailConfig.FROM_NAME),
            to_emails=guest_email,
            subject=f"Payment Request - Booking {booking['booking_id']}",
            html_content=email_html
        )

        sg = SendGridAPIClient(EmailConfig.SENDGRID_API_KEY)
        response = sg.send(message)

        if response.status_code in [200, 202]:
            return True, f"Payment request email sent to {guest_email}"
        else:
            return False, f"SendGrid error: {response.status_code}"

    except Exception as e:
        return False, f"Error: {str(e)}"


def process_pre_arrival_emails(club_filter=None, dry_run=False):
    """Process all pending pre-arrival emails"""
    bookings = get_upcoming_bookings_for_email(club_filter=club_filter)

    sent_count = 0
    failed_count = 0
    results = []

    for booking in bookings:
        if dry_run:
            results.append({
                'booking_id': booking['booking_id'],
                'email': booking['guest_email'],
                'status': 'would_send',
                'message': 'Dry run - email not sent'
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
    """Process all pending post-play emails"""
    bookings = get_recent_bookings_for_email(club_filter=club_filter)

    sent_count = 0
    failed_count = 0
    results = []

    for booking in bookings:
        if dry_run:
            results.append({
                'booking_id': booking['booking_id'],
                'email': booking['guest_email'],
                'status': 'would_send',
                'message': 'Dry run - email not sent'
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


def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash"""
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

def authenticate_user(username: str, password: str):
    """Authenticate user - handles both temp passwords and set passwords
    Returns (success, customer_id, full_name, must_change_password, user_id)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)
        cursor.execute("""
            SELECT id, password_hash, temp_password, customer_id, full_name,
                   is_active, must_change_password
            FROM dashboard_users
            WHERE username = %s;
        """, (username,))
        
        user = cursor.fetchone()
        
        if not user:
            cursor.close()
            conn.close()
            return False, None, None, False, None
        
        if not user['is_active']:
            cursor.close()
            conn.close()
            return False, None, None, False, None
        
        # Check if using temporary password (first login)
        if user['must_change_password'] and user['temp_password']:
            if password == user['temp_password']:
                cursor.close()
                conn.close()
                return True, user['customer_id'], user['full_name'], True, user['id']
        
        # Check regular password
        if user['password_hash'] and verify_password(password, user['password_hash']):
            cursor.close()
            conn.close()
            return True, user['customer_id'], user['full_name'], False, user['id']
        
        cursor.close()
        conn.close()
        return False, None, None, False, None
    except Exception as e:
        st.error(f"Authentication error: {e}")
        return False, None, None, False, None


def set_permanent_password(user_id: int, new_password: str):
    """Set permanent password and clear temp password"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        password_hash = hash_password(new_password)
        
        cursor.execute("""
            UPDATE dashboard_users
            SET password_hash = %s,
                temp_password = NULL,
                must_change_password = FALSE,
                last_login = NOW()
            WHERE id = %s;
        """, (password_hash, user_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error setting password: {e}")
        return False


def update_last_login(user_id: int):
    """Update last login timestamp"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE dashboard_users SET last_login = NOW() WHERE id = %s;", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        st.error(f"Error updating last login: {e}")


# ========================================
# BOOKING STATUS HELPERS
# ========================================
def get_status_icon(status: str) -> str:
    """Get timeline icon for booking status"""
    # Icons removed - using text-based status indicators only
    return ''


def get_status_color(status: str) -> str:
    """Get color class for status badge"""
    status_map = {
        'Inquiry': 'status-inquiry',
        'Requested': 'status-requested',
        'Confirmed': 'status-confirmed',
        'Booked': 'status-booked',
        'Rejected': 'status-rejected',
        'Cancelled': 'status-cancelled',
        'Pending': 'status-requested',
    }
    return status_map.get(status, 'status-inquiry')


def generate_status_progress_bar(current_status: str) -> str:
    """Generate a linear status progress bar showing booking workflow"""

    # Define the workflow stages - TeeMail colors
    stages = [
        {'name': 'Inquiry', 'color': '#3b82f6'},
        {'name': 'Requested', 'color': '#fbbf24'},
        {'name': 'Confirmed', 'color': '#a78bfa'},
        {'name': 'Booked', 'color': '#10b981'}
    ]

    # Handle special cases
    if current_status == 'Pending':
        current_status = 'Inquiry'

    # Check if rejected or cancelled
    is_rejected = current_status == 'Rejected'
    is_cancelled = current_status == 'Cancelled'

    if is_rejected or is_cancelled:
        status_color = '#ef4444' if is_rejected else '#ffffff'
        return f"""
        <div style='background: #059669; padding: 1rem; border-radius: 8px; border: 2px solid #10b981;'>
            <div style='display: flex; align-items: center; justify-content: center; gap: 0.75rem;'>
                <div style='width: 12px; height: 12px; border-radius: 50%; background: {status_color};'></div>
                <span style='color: {status_color}; font-weight: 700; font-size: 1rem; text-transform: uppercase; letter-spacing: 0.5px;'>{current_status}</span>
            </div>
        </div>
        """

    # Find current stage index
    current_index = next((i for i, s in enumerate(stages) if s['name'] == current_status), 0)

    # Generate HTML
    html = """
    <div style='background: #059669; padding: 1.25rem; border-radius: 8px; border: 2px solid #10b981;'>
        <div style='display: flex; align-items: center; justify-content: space-between; position: relative;'>
    """

    # Add connecting line
    html += """
        <div style='position: absolute; top: 0.75rem; left: 2rem; right: 2rem; height: 3px; background: #1e293b; z-index: 1;'></div>
    """

    # Add progress line (only up to current stage)
    progress_width = (current_index / (len(stages) - 1)) * 100 if len(stages) > 1 else 0
    html += f"""
        <div style='position: absolute; top: 0.75rem; left: 2rem; width: calc({progress_width}% - 2rem); height: 3px; background: linear-gradient(90deg, #3b82f6, #10b981); z-index: 2;'></div>
    """

    # Add stage nodes
    for i, stage in enumerate(stages):
        is_active = i <= current_index
        is_current = i == current_index

        bg_color = stage['color'] if is_active else '#1e293b'
        text_color = '#ffffff' if is_active else '#ffffff'
        border_color = stage['color'] if is_current else ('#10b981' if is_active else '#1e293b')
        box_shadow = '0 0 0 4px rgba(16, 185, 129, 0.4)' if is_current else 'none'

        html += f"""
        <div style='display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative;'>
            <div style='
                width: 1.5rem;
                height: 1.5rem;
                border-radius: 50%;
                background: {bg_color};
                border: 3px solid {border_color};
                box-shadow: {box_shadow};
                transition: all 0.3s ease;
            '>
            </div>
            <div style='
                margin-top: 0.5rem;
                font-size: 0.7rem;
                font-weight: {('700' if is_current else '600')};
                color: {text_color};
                text-transform: uppercase;
                letter-spacing: 0.5px;
                white-space: nowrap;
            '>{stage['name']}</div>
        </div>
        """

    html += """
        </div>
    </div>
    """

    return html


# ========================================
# SESSION STATE
# ========================================
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'customer_id' not in st.session_state:
    st.session_state.customer_id = None
if 'username' not in st.session_state:
    st.session_state.username = None
if 'full_name' not in st.session_state:
    st.session_state.full_name = None
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'must_change_password' not in st.session_state:
    st.session_state.must_change_password = False
if 'show_password_change' not in st.session_state:
    st.session_state.show_password_change = False


# ========================================
# LOGOUT FUNCTION
# ========================================
def logout():
    st.session_state.authenticated = False
    st.session_state.customer_id = None
    st.session_state.username = None
    st.session_state.full_name = None
    st.session_state.user_id = None
    st.session_state.must_change_password = False
    st.session_state.show_password_change = False


# ========================================
# STREAMLIT PAGE CONFIG
# ========================================
st.set_page_config(
    page_title="TeeMail Demo Dashboard",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========================================
# STYLING - TEEMAIL DEMO BRAND
# ========================================
st.markdown("""
    <style>
    .main {
        background: #0a0e1a;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
    }

    [data-testid="stSidebar"] {
        background: #1e293b;
        border-right: 1px solid #10b981;
    }
    
    .metric-card {
        background: linear-gradient(135deg, #059669 0%, #10b981 100%);
        padding: 1.75rem;
        border-radius: 12px;
        border: 2px solid #10b981;
        transition: all 0.3s ease;
        position: relative;
        overflow: hidden;
    }

    .metric-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: linear-gradient(90deg, #10b981, #3b82f6);
        opacity: 0;
        transition: opacity 0.3s ease;
    }

    .metric-card:hover {
        border-color: #10b981;
        box-shadow: 0 8px 24px rgba(16, 185, 129, 0.4);
        transform: translateY(-2px);
    }

    .metric-card:hover::before {
        opacity: 1;
    }
    
    .booking-id {
        font-size: 1rem;
        font-weight: 600;
        color: #ffffff;
        margin: 0;
        font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
        letter-spacing: 0.5px;
    }

    .booking-email {
        color: #ffffff;
        font-size: 0.875rem;
        margin: 0.375rem 0 0 0;
    }

    .timestamp {
        color: #ffffff;
        font-size: 0.8125rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-weight: 500;
    }

    .timestamp-value {
        color: #f9fafb;
        font-size: 0.875rem;
        font-weight: 600;
        margin-top: 0.25rem;
    }
    
    .stTextArea textarea {
        background: #1e293b !important;
        border: 2px solid #10b981 !important;
        border-radius: 0 0 8px 8px !important;
        color: #f9fafb !important;
        font-family: 'SF Mono', 'Monaco', 'Consolas', monospace !important;
        font-size: 0.8125rem !important;
        line-height: 1.7 !important;
        padding: 1rem !important;
    }

    .stTextArea textarea:disabled {
        background: #1e293b !important;
        color: #f9fafb !important;
        opacity: 1 !important;
        -webkit-text-fill-color: #f9fafb !important;
    }
    
    .status-timeline {
        display: inline-flex;
        align-items: center;
        gap: 0.625rem;
        background: #059669;
        padding: 0.5rem 1rem;
        border-radius: 8px;
        border: 2px solid #10b981;
    }

    .status-icon {
        font-size: 1.125rem;
        line-height: 1;
    }

    .status-badge {
        padding: 0.375rem 0.875rem;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.8125rem;
        display: inline-flex;
        align-items: center;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .status-inquiry {
        background: #3b82f6;
        color: #ffffff;
        border: 2px solid #3b82f6;
    }

    .status-requested {
        background: #fbbf24;
        color: #1f2937;
        border: 2px solid #fbbf24;
    }

    .status-confirmed {
        background: #a78bfa;
        color: #ffffff;
        border: 2px solid #a78bfa;
    }

    .status-booked {
        background: #10b981;
        color: #ffffff;
        border: 2px solid #10b981;
    }

    .status-rejected {
        background: #ef4444;
        color: #ffffff;
        border: 2px solid #ef4444;
    }

    .status-cancelled {
        background: #64748b;
        color: #ffffff;
        border: 2px solid #64748b;
    }
    
    .stButton > button {
        background: #10b981;
        color: white;
        border: none;
        padding: 0.625rem 1.25rem;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.875rem;
        transition: all 0.2s ease;
        width: 100%;
        letter-spacing: 0.3px;
        cursor: pointer;
    }

    .stButton > button:hover {
        background: #059669;
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
        transform: translateY(-1px);
    }

    .stButton > button:active {
        transform: translateY(0px);
    }
    
    h1 {
        color: #ffffff !important;
        font-weight: 700 !important;
        font-size: 1.875rem !important;
        letter-spacing: -0.5px !important;
    }

    h2, h3, h4, h5, h6 {
        color: #ffffff !important;
        font-weight: 600 !important;
    }

    p, span, div, label {
        color: #ffffff !important;
    }

    .user-badge {
        background: #3b82f6;
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 6px;
        font-size: 0.8125rem;
        font-weight: 600;
        display: inline-block;
        margin-bottom: 0.5rem;
        letter-spacing: 0.3px;
    }

    .club-badge {
        background: #10b981;
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 6px;
        font-size: 0.8125rem;
        font-weight: 600;
        display: inline-block;
        margin-bottom: 1rem;
        letter-spacing: 0.3px;
    }

    .data-label {
        color: #ffffff;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 0.5rem;
    }
    
    .streamlit-expanderHeader {
        background: #059669 !important;
        border-radius: 8px !important;
        border: 2px solid #10b981 !important;
        font-weight: 600 !important;
        font-size: 0.875rem !important;
        color: #f9fafb !important;
        transition: all 0.2s ease !important;
    }

    .streamlit-expanderHeader:hover {
        border-color: #10b981 !important;
        background: #10b981 !important;
    }

    .streamlit-expanderContent {
        background: #1e293b !important;
        border: 2px solid #10b981 !important;
        border-top: none !important;
        border-radius: 0 0 8px 8px !important;
    }

    /* Card Animation */
    @keyframes slideUp {
        from {
            opacity: 0;
            transform: translateY(20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    .booking-card {
        animation: slideUp 0.3s ease-out;
    }
    
    .stMultiSelect > div > div {
        background: #059669 !important;
        border: 2px solid #10b981 !important;
        border-radius: 6px !important;
    }

    .stDateInput > div > div {
        background: #059669 !important;
        border: 2px solid #10b981 !important;
        border-radius: 6px !important;
    }
    
    #MainMenu {visibility: hidden;} 
    footer {visibility: hidden;} 
    header {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)


# ========================================
# PASSWORD CHANGE SCREEN
# ========================================
if st.session_state.show_password_change:
    st.markdown("""
        <style>
        .password-container {
            max-width: 500px;
            margin: 100px auto;
            padding: 2.5rem;
            background: linear-gradient(135deg, #059669 0%, #10b981 100%);
            border-radius: 16px;
            border: 2px solid #10b981;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
        }
        .password-title {
            color: #ffffff;
            font-size: 1.8rem;
            font-weight: 700;
            text-align: center;
            margin-bottom: 0.5rem;
        }
        .password-subtitle {
            color: #f9fafb;
            text-align: center;
            margin-bottom: 2rem;
            font-size: 0.95rem;
        }
        </style>
    """, unsafe_allow_html=True)

    st.markdown("""
        <div class="password-container">
            <div class="password-title">Set Your Password</div>
            <div class="password-subtitle">First-time setup - create your secure password</div>
        </div>
    """, unsafe_allow_html=True)
    
    with st.form("password_setup_form"):
        st.info(f"Welcome, **{st.session_state.full_name}**! Please create a secure password for your account.")
        
        new_password = st.text_input("New Password", type="password", key="new_pass")
        confirm_password = st.text_input("Confirm Password", type="password", key="confirm_pass")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            submit = st.form_submit_button("Set Password", use_container_width=True)
        with col2:
            cancel = st.form_submit_button("Cancel", use_container_width=True)
        
        if cancel:
            logout()
            st.rerun()
        
        if submit:
            if not new_password or not confirm_password:
                st.error("Please fill in both password fields")
            elif new_password != confirm_password:
                st.error("Passwords do not match")
            elif len(new_password) < 8:
                st.error("Password must be at least 8 characters")
            else:
                if set_permanent_password(st.session_state.user_id, new_password):
                    update_last_login(st.session_state.user_id)
                    st.session_state.show_password_change = False
                    st.session_state.must_change_password = False
                    st.success("Password set successfully!")
                    st.rerun()
                else:
                    st.error("Error setting password. Please try again.")
    
    st.stop()


# ========================================
# LOGIN SCREEN
# ========================================
if not st.session_state.authenticated:
    st.markdown("""
        <style>
        .login-logo-container {
            text-align: center;
            margin-top: 80px;
            margin-bottom: 2rem;
        }
        .login-subtitle {
            color: #ffffff;
            text-align: center;
            margin-bottom: 3rem;
            font-size: 1.1rem;
            font-weight: 500;
        }
        </style>
    """, unsafe_allow_html=True)

    # Center the logo
    st.markdown("""
        <div style='display: flex; justify-content: center; align-items: center;'>
            <img src='https://raw.githubusercontent.com/jimbobirecode/TeeMail-Assests/main/output-onlinepngtools.png' width='300' style='display: block; margin: 0 auto;'/>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("""
        <div class="login-subtitle">Booking Management System</div>
    """, unsafe_allow_html=True)
    
    with st.form("login_form"):
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        submit = st.form_submit_button("Login", use_container_width=True)
        
        if submit:
            if username and password:
                success, customer_id, full_name, must_change, user_id = authenticate_user(username, password)
                
                if success:
                    st.session_state.authenticated = True
                    st.session_state.customer_id = customer_id
                    st.session_state.username = username
                    st.session_state.full_name = full_name
                    st.session_state.user_id = user_id

                    if must_change:
                        st.session_state.must_change_password = True
                        st.session_state.show_password_change = True
                        st.success("Please set your password...")
                        st.rerun()
                    else:
                        update_last_login(user_id)
                        st.success("Login successful!")
                        st.rerun()
                else:
                    st.error("Invalid username or password")
            else:
                st.error("Please enter username and password")
    
    st.markdown("""
        <div style='text-align: center; color: #ffffff; font-size: 0.85rem; margin-top: 2rem;'>
            <p>First time? Use your temporary password</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.stop()


# ========================================
# LOAD BOOKINGS
# ========================================
@st.cache_data(ttl=10)
def load_bookings_from_db(club_filter):
    """Load bookings directly from PostgreSQL database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)

        cursor.execute("""
            SELECT
                id, booking_id, guest_email, date, tee_time, players, total,
                status, note, club, timestamp, customer_confirmed_at,
                updated_at, updated_by, created_at,
                hotel_required, hotel_checkin, hotel_checkout,
                golf_courses, selected_tee_times,
                is_tour_operator, payment_status, deposit_percentage, total_paid
            FROM bookings
            WHERE club = %s
            ORDER BY timestamp DESC
        """, (club_filter,))

        bookings = cursor.fetchall()
        cursor.close()
        conn.close()

        if not bookings:
            return pd.DataFrame(), 'postgresql'

        df = pd.DataFrame(bookings)

        # Ensure all datetime columns are properly converted
        for col in ['timestamp', 'customer_confirmed_at', 'updated_at', 'created_at', 'hotel_checkin', 'hotel_checkout']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')

        # Ensure tee_time exists and handle None/NaN values
        if 'tee_time' not in df.columns:
            df['tee_time'] = 'Not Specified'
        else:
            df['tee_time'] = df['tee_time'].fillna('Not Specified')

        # Extract tee times from note content if not already set
        for idx in df.index:
            current_tee_time = df.at[idx, 'tee_time']
            if current_tee_time in ['Not Specified', None, ''] or pd.isna(current_tee_time):
                note_content = df.at[idx, 'note']
                extracted_time = extract_tee_time_from_note(note_content)
                if extracted_time:
                    df.at[idx, 'tee_time'] = extracted_time

        # Ensure note column exists and handle None/NaN
        if 'note' not in df.columns:
            df['note'] = 'No additional information provided'
        else:
            df['note'] = df['note'].fillna('No additional information provided')

        # Ensure all required columns have proper defaults
        if 'status' not in df.columns:
            df['status'] = 'Inquiry'

        if 'players' not in df.columns:
            df['players'] = 1
        else:
            df['players'] = df['players'].fillna(1)

        if 'total' not in df.columns:
            df['total'] = 0.0
        else:
            df['total'] = df['total'].fillna(0.0)

        if 'guest_email' not in df.columns:
            df['guest_email'] = 'No email provided'
        else:
            df['guest_email'] = df['guest_email'].fillna('No email provided')

        if 'booking_id' not in df.columns:
            df['booking_id'] = df.index.map(lambda x: f'BOOK-{x:04d}')

        # Ensure hotel_required column exists with default False
        if 'hotel_required' not in df.columns:
            df['hotel_required'] = False
        else:
            df['hotel_required'] = df['hotel_required'].fillna(False)

        # Ensure golf_courses and selected_tee_times columns exist
        if 'golf_courses' not in df.columns:
            df['golf_courses'] = ''
        else:
            df['golf_courses'] = df['golf_courses'].fillna('')

        if 'selected_tee_times' not in df.columns:
            df['selected_tee_times'] = ''
        else:
            df['selected_tee_times'] = df['selected_tee_times'].fillna('')

        return df, 'postgresql'
    except Exception as e:
        st.error(f"Database error: {e}")
        import traceback
        st.error(f"Details: {traceback.format_exc()}")
        return pd.DataFrame(), 'error'


def update_booking_status(booking_id: str, new_status: str, updated_by: str):
    """Update booking status in database and return True to trigger filter adjustment"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE bookings
            SET status = %s, updated_at = NOW(), updated_by = %s
            WHERE booking_id = %s;
        """, (new_status, updated_by, booking_id))

        conn.commit()
        cursor.close()
        conn.close()

        # Store the new status in session state to auto-include in filter
        if 'auto_include_status' not in st.session_state:
            st.session_state.auto_include_status = set()
        st.session_state.auto_include_status.add(new_status)

        return True
    except Exception as e:
        st.error(f"Error updating status: {e}")
        return False


def update_booking_tee_time(booking_id: str, tee_time: str):
    """Update booking tee_time in database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE bookings
            SET tee_time = %s, updated_at = NOW()
            WHERE booking_id = %s;
        """, (tee_time, booking_id))

        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error updating tee time: {e}")
        return False


def fix_all_tee_times(club_filter):
    """Extract and update tee times for all bookings with missing tee times"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)

        # Get all bookings with missing or "Not Specified" tee times
        cursor.execute("""
            SELECT id, booking_id, note, tee_time
            FROM bookings
            WHERE club = %s
              AND (tee_time IS NULL OR tee_time = 'Not Specified' OR tee_time = '');
        """, (club_filter,))

        bookings = cursor.fetchall()

        if not bookings:
            cursor.close()
            conn.close()
            return 0, 0

        updated_count = 0
        not_found_count = 0

        for booking in bookings:
            note = booking['note']
            extracted_time = extract_tee_time_from_note(note)

            if extracted_time:
                # Update the booking
                cursor.execute("""
                    UPDATE bookings
                    SET tee_time = %s, updated_at = NOW()
                    WHERE id = %s;
                """, (extracted_time, booking['id']))
                updated_count += 1
            else:
                not_found_count += 1

        # Commit all updates
        conn.commit()
        cursor.close()
        conn.close()

        return updated_count, not_found_count

    except Exception as e:
        st.error(f"Error fixing tee times: {e}")
        return 0, 0


def delete_booking(booking_id: str):
    """Delete a booking from the database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM bookings
            WHERE booking_id = %s;
        """, (booking_id,))

        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error deleting booking: {e}")
        return False


def update_booking_note(booking_id: str, note: str):
    """Update booking note in database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE bookings
            SET note = %s, updated_at = NOW()
            WHERE booking_id = %s;
        """, (note, booking_id))

        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error updating note: {e}")
        return False


# ========================================
# NOTIFY PLATFORM INTEGRATION
# ========================================
def prepare_booking_data_for_export(df, format_type='json'):
    """
    Prepare booking data for export to Notify platform.
    Supports JSON, API-ready dict, and CSV formats.
    """
    export_data = []
    for _, row in df.iterrows():
        booking_record = {
            'booking_id': str(row.get('booking_id', '')),
            'customer_email': str(row.get('guest_email', '')),
            'booking_date': row['date'].strftime('%Y-%m-%d') if pd.notna(row.get('date')) else '',
            'tee_time': str(row.get('tee_time', '')),
            'players': int(row.get('players', 1)),
            'total_amount': float(row.get('total', 0)),
            'status': str(row.get('status', '')),
            'golf_courses': str(row.get('golf_courses', '')),
            'hotel_required': bool(row.get('hotel_required', False)),
            'created_at': row['timestamp'].strftime('%Y-%m-%dT%H:%M:%SZ') if pd.notna(row.get('timestamp')) else '',
            'club': str(row.get('club', ''))
        }
        export_data.append(booking_record)

    return export_data


def export_to_json(df):
    """Export booking data to JSON format for Notify platform"""
    data = prepare_booking_data_for_export(df, 'json')
    return json.dumps({
        'export_timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'total_records': len(data),
        'bookings': data
    }, indent=2)


def export_to_api_format(df):
    """Export booking data in API-ready format for webhook/API integration"""
    data = prepare_booking_data_for_export(df, 'api')
    return {
        'meta': {
            'export_timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'total_records': len(data),
            'format_version': '1.0'
        },
        'data': data
    }


def push_to_notify_api(df, api_endpoint, api_key=None):
    """
    Push booking data to external Notify platform via API.
    Returns success status and response message.
    """
    try:
        payload = export_to_api_format(df)
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        response = requests.post(
            api_endpoint,
            json=payload,
            headers=headers,
            timeout=30
        )

        if response.status_code in [200, 201, 202]:
            return True, f"Successfully pushed {len(payload['data'])} records to Notify platform"
        else:
            return False, f"API returned status {response.status_code}: {response.text[:200]}"
    except requests.exceptions.Timeout:
        return False, "Request timed out. Please try again."
    except requests.exceptions.ConnectionError:
        return False, "Could not connect to the Notify platform. Please check the endpoint URL."
    except Exception as e:
        return False, f"Error pushing to API: {str(e)}"


def export_notify_csv(df):
    """Export booking data in CSV format optimized for Notify platform import"""
    export_df = pd.DataFrame(prepare_booking_data_for_export(df, 'csv'))
    return export_df.to_csv(index=False)


# ========================================
# WAITLIST MODULE FUNCTIONS
# ========================================
def create_waitlist_table_if_not_exists():
    """Ensure waitlist table exists in database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS waitlist (
                id SERIAL PRIMARY KEY,
                waitlist_id VARCHAR(50) UNIQUE NOT NULL,
                guest_email VARCHAR(255) NOT NULL,
                guest_name VARCHAR(255),
                requested_date DATE NOT NULL,
                preferred_time VARCHAR(50),
                time_flexibility VARCHAR(50) DEFAULT 'Flexible',
                players INTEGER DEFAULT 1,
                golf_course VARCHAR(255),
                status VARCHAR(50) DEFAULT 'Waiting',
                priority INTEGER DEFAULT 5,
                notes TEXT,
                notification_sent BOOLEAN DEFAULT FALSE,
                notification_sent_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                club VARCHAR(100) NOT NULL
            );
        """)
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error creating waitlist table: {e}")
        return False


def load_waitlist_from_db(club_filter):
    """Load waitlist entries from database"""
    try:
        create_waitlist_table_if_not_exists()
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)

        cursor.execute("""
            SELECT * FROM waitlist
            WHERE club = %s
            ORDER BY requested_date ASC, priority DESC, created_at ASC
        """, (club_filter,))

        waitlist = cursor.fetchall()
        cursor.close()
        conn.close()

        if not waitlist:
            return pd.DataFrame()

        df = pd.DataFrame(waitlist)

        # Convert date columns
        for col in ['requested_date', 'created_at', 'updated_at', 'notification_sent_at']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')

        return df
    except Exception as e:
        st.error(f"Error loading waitlist: {e}")
        return pd.DataFrame()


def add_to_waitlist(guest_email, guest_name, requested_date, preferred_time,
                    time_flexibility, players, golf_course, notes, club, priority=5):
    """Add a new entry to the waitlist"""
    try:
        create_waitlist_table_if_not_exists()
        conn = get_db_connection()
        cursor = conn.cursor()

        # Generate waitlist ID
        waitlist_id = f"WL-{datetime.now().strftime('%Y%m%d%H%M%S')}-{hash(guest_email) % 10000:04d}"

        cursor.execute("""
            INSERT INTO waitlist (
                waitlist_id, guest_email, guest_name, requested_date, preferred_time,
                time_flexibility, players, golf_course, notes, club, priority
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (waitlist_id, guest_email, guest_name, requested_date, preferred_time,
              time_flexibility, players, golf_course, notes, club, priority))

        conn.commit()
        cursor.close()
        conn.close()
        return True, waitlist_id
    except Exception as e:
        st.error(f"Error adding to waitlist: {e}")
        return False, None


def update_waitlist_status(waitlist_id, new_status, send_notification=False):
    """Update waitlist entry status"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if send_notification:
            cursor.execute("""
                UPDATE waitlist
                SET status = %s, notification_sent = TRUE,
                    notification_sent_at = NOW(), updated_at = NOW()
                WHERE waitlist_id = %s
            """, (new_status, waitlist_id))
        else:
            cursor.execute("""
                UPDATE waitlist
                SET status = %s, updated_at = NOW()
                WHERE waitlist_id = %s
            """, (new_status, waitlist_id))

        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error updating waitlist: {e}")
        return False


def delete_waitlist_entry(waitlist_id):
    """Delete a waitlist entry"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM waitlist WHERE waitlist_id = %s", (waitlist_id,))

        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error deleting waitlist entry: {e}")
        return False


def get_waitlist_matches(club_filter, available_date, available_time=None):
    """Find waitlist entries that match an available tee time"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)

        query = """
            SELECT * FROM waitlist
            WHERE club = %s
            AND requested_date = %s
            AND status = 'Waiting'
            ORDER BY priority DESC, created_at ASC
        """
        cursor.execute(query, (club_filter, available_date))

        matches = cursor.fetchall()
        cursor.close()
        conn.close()

        return pd.DataFrame(matches) if matches else pd.DataFrame()
    except Exception as e:
        st.error(f"Error finding waitlist matches: {e}")
        return pd.DataFrame()


def convert_waitlist_to_booking(waitlist_entry, tee_time, total_amount=0):
    """Convert a waitlist entry to a booking"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Generate booking ID
        booking_id = f"BOOK-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        cursor.execute("""
            INSERT INTO bookings (
                booking_id, guest_email, date, tee_time, players, total,
                status, note, club, timestamp, golf_courses
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
        """, (
            booking_id,
            waitlist_entry['guest_email'],
            waitlist_entry['requested_date'],
            tee_time,
            waitlist_entry['players'],
            total_amount,
            'Confirmed',
            f"Converted from waitlist: {waitlist_entry['waitlist_id']}. {waitlist_entry.get('notes', '')}",
            waitlist_entry['club'],
            waitlist_entry.get('golf_course', '')
        ))

        # Update waitlist status
        cursor.execute("""
            UPDATE waitlist
            SET status = 'Converted', updated_at = NOW()
            WHERE waitlist_id = %s
        """, (waitlist_entry['waitlist_id'],))

        conn.commit()
        cursor.close()
        conn.close()
        return True, booking_id
    except Exception as e:
        st.error(f"Error converting waitlist to booking: {e}")
        return False, None


# ========================================
# INBOUND EMAILS FUNCTIONS
# ========================================
def load_emails_by_booking_id(booking_id, guest_email=None):
    """Load inbound emails for a specific booking

    Matches emails by:
    1. booking_id field (if populated)
    2. from_email matching guest_email (for emails not yet linked)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)

        # Query emails that either have the booking_id OR match the guest email
        if guest_email:
            cursor.execute("""
                SELECT * FROM inbound_emails
                WHERE booking_id = %s
                   OR (booking_id IS NULL AND from_email ILIKE %s)
                   OR (booking_id IS NULL AND to_email ILIKE %s)
                ORDER BY received_at DESC
            """, (booking_id, f"%{guest_email}%", f"%{guest_email}%"))
        else:
            cursor.execute("""
                SELECT * FROM inbound_emails
                WHERE booking_id = %s
                ORDER BY received_at DESC
            """, (booking_id,))

        emails = cursor.fetchall()
        cursor.close()
        conn.close()

        if not emails:
            return []

        # Convert to list of dicts and format dates
        result = []
        for email in emails:
            email_dict = dict(email)
            # Convert timestamp columns to formatted strings
            if 'received_at' in email_dict and email_dict['received_at']:
                email_dict['received_at_formatted'] = email_dict['received_at'].strftime('%b %d, %Y %I:%M %p')
            else:
                email_dict['received_at_formatted'] = 'N/A'
            result.append(email_dict)

        return result
    except Exception as e:
        st.error(f"Error loading emails: {e}")
        return []


# ========================================
# ANALYTICS HELPER FUNCTIONS
# ========================================
def calculate_lead_times(df):
    """Calculate average lead time between inquiry and booking"""
    lead_times = []

    # Calculate lead time as days between booking creation and tee date
    for _, row in df.iterrows():
        if pd.notna(row.get('timestamp')) and pd.notna(row.get('date')):
            lead_time = (row['date'] - row['timestamp']).days
            if lead_time >= 0:  # Only positive lead times
                lead_times.append({
                    'booking_id': row['booking_id'],
                    'lead_time_days': lead_time,
                    'status': row['status']
                })

    return pd.DataFrame(lead_times)


def calculate_customer_inquiry_frequency(df):
    """Calculate booking inquiry frequency by customer for targeted marketing"""
    customer_stats = df.groupby('guest_email').agg({
        'booking_id': 'count',
        'total': 'sum',
        'players': 'sum',
        'status': lambda x: (x == 'Booked').sum()
    }).reset_index()

    customer_stats.columns = ['Customer Email', 'Total Inquiries', 'Total Revenue',
                              'Total Players', 'Completed Bookings']

    # Calculate conversion rate
    customer_stats['Conversion Rate'] = (
        customer_stats['Completed Bookings'] / customer_stats['Total Inquiries'] * 100
    ).round(1)

    # Calculate average booking value
    customer_stats['Avg Booking Value'] = (
        customer_stats['Total Revenue'] / customer_stats['Total Inquiries']
    ).round(2)

    return customer_stats.sort_values('Total Inquiries', ascending=False)


def calculate_golf_course_popularity(df):
    """Calculate booking statistics by golf course"""
    # Filter rows with golf course data
    course_df = df[df['golf_courses'].notna() & (df['golf_courses'] != '')]

    if course_df.empty:
        return pd.DataFrame()

    course_stats = course_df.groupby('golf_courses').agg({
        'booking_id': 'count',
        'total': 'sum',
        'players': 'sum',
        'status': lambda x: (x == 'Booked').sum()
    }).reset_index()

    course_stats.columns = ['Golf Course', 'Total Requests', 'Total Revenue',
                            'Total Players', 'Confirmed Bookings']

    # Calculate conversion and average values
    course_stats['Conversion Rate'] = (
        course_stats['Confirmed Bookings'] / course_stats['Total Requests'] * 100
    ).round(1)
    course_stats['Avg Revenue per Request'] = (
        course_stats['Total Revenue'] / course_stats['Total Requests']
    ).round(2)

    return course_stats.sort_values('Total Requests', ascending=False)


def identify_marketing_segments(df):
    """
    Identify marketing segments including frequent non-booking leads.
    Returns segmented customer data for targeted campaigns.
    """
    customer_stats = df.groupby('guest_email').agg({
        'booking_id': 'count',
        'total': 'sum',
        'status': lambda x: list(x),
        'timestamp': 'max'
    }).reset_index()

    customer_stats.columns = ['Customer Email', 'Total Contacts', 'Total Revenue',
                              'Statuses', 'Last Contact']

    # Calculate completed bookings
    customer_stats['Completed Bookings'] = customer_stats['Statuses'].apply(
        lambda x: sum(1 for s in x if s == 'Booked')
    )

    # Define segments
    segments = []
    for _, row in customer_stats.iterrows():
        total_contacts = row['Total Contacts']
        completed = row['Completed Bookings']
        revenue = row['Total Revenue']

        if total_contacts >= 3 and completed == 0:
            segment = 'Frequent Non-Booker'
            priority = 'High'
            action = 'Targeted re-engagement campaign'
        elif total_contacts >= 2 and completed == 0:
            segment = 'Repeat Inquirer'
            priority = 'Medium'
            action = 'Follow-up offer campaign'
        elif completed > 0 and revenue > 500:
            segment = 'High-Value Customer'
            priority = 'VIP'
            action = 'Loyalty rewards program'
        elif completed > 0:
            segment = 'Converted Customer'
            priority = 'Standard'
            action = 'Retention campaign'
        else:
            segment = 'Single Inquiry'
            priority = 'Low'
            action = 'General marketing list'

        segments.append({
            'Customer Email': row['Customer Email'],
            'Total Contacts': total_contacts,
            'Completed Bookings': completed,
            'Total Revenue': revenue,
            'Last Contact': row['Last Contact'],
            'Segment': segment,
            'Priority': priority,
            'Recommended Action': action
        })

    return pd.DataFrame(segments)


# ========================================
# MAIN DASHBOARD
# ========================================

with st.sidebar:
    # TeeMail Demo logo
    st.markdown("""
        <div style='display: flex; justify-content: center; align-items: center; padding: 1rem 0.5rem; margin-bottom: 1rem;'>
            <img src='https://raw.githubusercontent.com/jimbobirecode/TeeMail-Assests/main/output-onlinepngtools.png' width='180' style='display: block;'/>
        </div>
    """, unsafe_allow_html=True)
    st.markdown("""
        <div style='text-align: center; margin-top: 0.5rem;'>
            <p style='color: #f9fafb; font-size: 0.9rem; margin: 0; font-weight: 600; letter-spacing: 0.5px;'>Booking Dashboard</p>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='height: 1px; background: #3b82f6; margin: 1rem 0 1.5rem 0;'></div>", unsafe_allow_html=True)

    st.markdown(f"<div class='user-badge'>{st.session_state.full_name}</div>", unsafe_allow_html=True)

    # Get club display name - always show TeeMail Demo
    club_display = get_club_display_name(st.session_state.customer_id) if st.session_state.customer_id else 'TeeMail Demo'
    # Force TeeMail Demo display
    club_display = 'TeeMail Demo'
    st.markdown(f"<div class='club-badge'>{club_display}</div>", unsafe_allow_html=True)

    st.markdown("<div style='height: 1px; background: #3b82f6; margin: 1.5rem 0;'></div>", unsafe_allow_html=True)

    if st.button("Logout", use_container_width=True):
        logout()
        st.rerun()

    st.markdown("<div style='height: 1px; background: #3b82f6; margin: 1.5rem 0;'></div>", unsafe_allow_html=True)

    # Navigation menu
    st.markdown("#### Navigation")
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "Bookings"

    nav_options = ["Bookings", "Waitlist", "Reports & Analytics", "Marketing Segmentation", "Email Automation", "Notify Integration"]
    current_index = nav_options.index(st.session_state.current_page) if st.session_state.current_page in nav_options else 0

    page = st.radio(
        "Select View",
        nav_options,
        index=current_index,
        key="nav_radio",
        label_visibility="collapsed"
    )

    # Only update and rerun if page actually changed
    if page != st.session_state.current_page:
        st.session_state.current_page = page
        st.rerun()

    st.markdown("<div style='height: 1px; background: #3b82f6; margin: 1.5rem 0;'></div>", unsafe_allow_html=True)

    # Only show filters for Bookings page
    if page == "Bookings":
        st.markdown("#### Filters")

        # Initialize filter state
        if 'auto_include_status' not in st.session_state:
            st.session_state.auto_include_status = set()
        if 'clicked_status_filter' not in st.session_state:
            st.session_state.clicked_status_filter = None
        if 'date_filter_preset' not in st.session_state:
            st.session_state.date_filter_preset = "Next 30 Days"

        # Date preset selector
        date_preset = st.selectbox(
            "Date Preset",
            ["All Bookings", "Past 30 Days", "Past 7 Days", "Today", "Next 7 Days", "Next 30 Days", "Next 60 Days", "Next 90 Days", "All Upcoming", "Custom"],
            index=5  # Default to "Next 30 Days"
        )

        # Calculate date range based on preset
        if date_preset == "All Bookings":
            date_range = None  # Show all bookings including those with NULL dates
        elif date_preset == "Past 30 Days":
            date_range = (datetime.now().date() - timedelta(days=30), datetime.now().date())
        elif date_preset == "Past 7 Days":
            date_range = (datetime.now().date() - timedelta(days=7), datetime.now().date())
        elif date_preset == "Today":
            date_range = (datetime.now().date(), datetime.now().date())
        elif date_preset == "Next 7 Days":
            date_range = (datetime.now().date(), datetime.now().date() + timedelta(days=7))
        elif date_preset == "Next 30 Days":
            date_range = (datetime.now().date(), datetime.now().date() + timedelta(days=30))
        elif date_preset == "Next 60 Days":
            date_range = (datetime.now().date(), datetime.now().date() + timedelta(days=60))
        elif date_preset == "Next 90 Days":
            date_range = (datetime.now().date(), datetime.now().date() + timedelta(days=90))
        elif date_preset == "All Upcoming":
            date_range = None  # Show all upcoming bookings including those with NULL dates
        else:  # Custom
            date_range = st.date_input(
                "Custom Date Range",
                value=(datetime.now().date(), datetime.now().date() + timedelta(days=30))
            )

        # Status filter - if clicked from metric card, use that
        if st.session_state.clicked_status_filter:
            if st.session_state.clicked_status_filter == "Inquiry+Pending":
                default_statuses = ["Inquiry", "Pending"]
            else:
                default_statuses = [st.session_state.clicked_status_filter]
        else:
            # For "All Bookings" and "All Upcoming", include all statuses by default
            if date_preset in ["All Bookings", "All Upcoming"]:
                default_statuses = ["Inquiry", "Requested", "Confirmed", "Booked", "Rejected", "Cancelled", "Pending"]
            else:
                # For other presets, show only active statuses by default
                default_statuses = ["Inquiry", "Requested", "Confirmed", "Booked", "Pending"]
            # Merge with auto-included ones
            default_statuses = list(set(default_statuses) | st.session_state.auto_include_status)

        status_filter = st.multiselect(
            "Status",
            ["Inquiry", "Requested", "Confirmed", "Booked", "Rejected", "Cancelled", "Pending"],
            default=default_statuses
        )

        # Small group filter
        show_small_groups_only = st.checkbox(
            "🏌️ Show only 1-2 player bookings",
            value=False,
            help="Filter to show only single or 2-ball bookings"
        )

        # Clear filter button
        if st.button("Clear All Filters", use_container_width=True):
            st.session_state.clicked_status_filter = None
            st.cache_data.clear()
            st.rerun()

# ========================================
# BOOKINGS VIEW
# ========================================
if page == "Bookings":
    st.markdown("""
        <h1 style='margin-bottom: 1rem;'>TeeMail Demo Dashboard</h1>
    """, unsafe_allow_html=True)

    # Header with refresh button
    header_col1, header_col2 = st.columns([4, 1])
    with header_col1:
        st.markdown("""
            <h2 style='margin-bottom: 0.5rem;'>Booking Requests</h2>
            <p style='color: #ffffff; margin-bottom: 1rem; font-size: 0.9375rem;'>Manage and track all incoming tee time requests</p>
        """, unsafe_allow_html=True)
    with header_col2:
        if st.button("Refresh", key="refresh_bookings", use_container_width=True, help="Refresh booking data"):
            st.cache_data.clear()
            st.rerun()
    
    # Show active filter indicator
    if st.session_state.clicked_status_filter:
        st.markdown(f"""
            <div style='background: #1e3a8a; border: 2px solid #10b981; border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 1.5rem; display: flex; align-items: center; justify-content: space-between;'>
                <div style='display: flex; align-items: center; gap: 0.5rem;'>
                    <span style='color: #3b82f6; font-weight: 600; font-size: 1rem;'>Filtering by: {st.session_state.clicked_status_filter}</span>
                </div>
            </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("<div style='margin-bottom: 1rem;'></div>", unsafe_allow_html=True)
    
    df, source = load_bookings_from_db('demo')

    if df.empty:
        st.warning("No bookings found for club='demo' in database")
        st.stop()

    # Create a date-only filtered dataframe for counting "Showing" numbers
    # This ensures the counts reflect bookings within the date range, regardless of status filter
    date_filtered_df = df.copy()

    # Handle date range filtering for date_filtered_df
    # Skip date filtering if date_range is None (for "All Bookings" and "All Upcoming")
    if date_range and date_range is not None:
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
            # Convert date objects to datetime for comparison
            start_datetime = pd.to_datetime(start_date)
            end_datetime = pd.to_datetime(end_date)
            date_filtered_df = date_filtered_df[
                (date_filtered_df['date'] >= start_datetime) &
                (date_filtered_df['date'] <= end_datetime)
            ]
        elif hasattr(date_range, '__len__') and len(date_range) == 2:
            start_date, end_date = date_range[0], date_range[1]
            # Convert date objects to datetime for comparison
            start_datetime = pd.to_datetime(start_date)
            end_datetime = pd.to_datetime(end_date)
            date_filtered_df = date_filtered_df[
                (date_filtered_df['date'] >= start_datetime) &
                (date_filtered_df['date'] <= end_datetime)
            ]

    # Create the fully filtered dataframe (by both status and date) for displaying bookings
    filtered_df = date_filtered_df.copy()
    if status_filter:
        filtered_df = filtered_df[filtered_df['status'].isin(status_filter)]

    # Apply small groups filter if enabled
    if show_small_groups_only:
        filtered_df = filtered_df[filtered_df['players'] <= 2]

    col1, col2, col3, col4 = st.columns(4)

    # Calculate counts for all statuses (before any filtering)
    all_inquiry_count = len(df[df['status'].isin(['Inquiry', 'Pending'])])
    all_requested_count = len(df[df['status'] == 'Requested'])
    all_confirmed_count = len(df[df['status'] == 'Confirmed'])
    all_booked_count = len(df[df['status'] == 'Booked'])

    with col1:
        inquiry_count = len(date_filtered_df[date_filtered_df['status'].isin(['Inquiry', 'Pending'])])
        if st.button(f"Inquiry\n{all_inquiry_count}", key="filter_inquiry", use_container_width=True, help="Click to filter Inquiry status"):
            st.session_state.clicked_status_filter = "Inquiry+Pending"
            st.cache_data.clear()
            st.rerun()
        st.markdown(f"<div style='text-align: center; color: #ffffff; font-size: 0.75rem; margin-top: -0.5rem;'>Showing: {inquiry_count}</div>", unsafe_allow_html=True)

    with col2:
        requested_count = len(date_filtered_df[date_filtered_df['status'] == 'Requested'])
        if st.button(f"Requested\n{all_requested_count}", key="filter_requested", use_container_width=True, help="Click to filter Requested status"):
            st.session_state.clicked_status_filter = "Requested"
            st.cache_data.clear()
            st.rerun()
        st.markdown(f"<div style='text-align: center; color: #ffffff; font-size: 0.75rem; margin-top: -0.5rem;'>Showing: {requested_count}</div>", unsafe_allow_html=True)

    with col3:
        confirmed_count = len(date_filtered_df[date_filtered_df['status'] == 'Confirmed'])
        if st.button(f"Confirmed\n{all_confirmed_count}", key="filter_confirmed", use_container_width=True, help="Click to filter Confirmed status"):
            st.session_state.clicked_status_filter = "Confirmed"
            st.cache_data.clear()
            st.rerun()
        st.markdown(f"<div style='text-align: center; color: #ffffff; font-size: 0.75rem; margin-top: -0.5rem;'>Showing: {confirmed_count}</div>", unsafe_allow_html=True)

    with col4:
        booked_count = len(date_filtered_df[date_filtered_df['status'] == 'Booked'])
        if st.button(f"Booked\n{all_booked_count}", key="filter_booked", use_container_width=True, help="Click to filter Booked status"):
            st.session_state.clicked_status_filter = "Booked"
            st.cache_data.clear()
            st.rerun()
        st.markdown(f"<div style='text-align: center; color: #ffffff; font-size: 0.75rem; margin-top: -0.5rem;'>Showing: {booked_count}</div>", unsafe_allow_html=True)
    
    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)
    
    # Format date range string
    if date_range:
        if isinstance(date_range, tuple) and len(date_range) == 2:
            date_str = f"{date_range[0].strftime('%b %d')} to {date_range[1].strftime('%b %d, %Y')}"
        elif hasattr(date_range, '__len__') and len(date_range) == 2:
            date_str = f"{date_range[0].strftime('%b %d')} to {date_range[1].strftime('%b %d, %Y')}"
        else:
            date_str = "all dates"
    else:
        date_str = "all dates"
    
    # Search bar
    search_term = st.text_input(
        "🔍 Search bookings",
        placeholder="Search by name, email, booking ID, golf course...",
        key="booking_search"
    )

    # Apply search filter
    if search_term:
        search_lower = search_term.lower()
        filtered_df = filtered_df[
            filtered_df['guest_email'].astype(str).str.lower().str.contains(search_lower, na=False) |
            filtered_df['guest_name'].astype(str).str.lower().str.contains(search_lower, na=False) |
            filtered_df['booking_id'].astype(str).str.lower().str.contains(search_lower, na=False) |
            filtered_df.get('golf_courses', pd.Series(dtype=str)).astype(str).str.lower().str.contains(search_lower, na=False) |
            filtered_df.get('note', pd.Series(dtype=str)).astype(str).str.lower().str.contains(search_lower, na=False)
        ]

    st.markdown(f"""
        <div style='margin-bottom: 1.5rem;'>
            <h3 style='color: #f9fafb; font-weight: 600; font-size: 1.125rem;'>{len(filtered_df)} Active Requests</h3>
            <p style='color: #64748b; font-size: 0.875rem; margin-top: 0.25rem;'>Showing bookings from {date_str}</p>
        </div>
    """, unsafe_allow_html=True)

    # Add visual separator
    st.markdown("<div style='margin-bottom: 1rem;'></div>", unsafe_allow_html=True)

    # ========================================
    # BOOKING CARDS - ENHANCED VERSION
    # ========================================
    for idx, booking in filtered_df.iterrows():
        status_icon = get_status_icon(booking['status'])
        status_class = get_status_color(booking['status'])
    
        tee_time_display = booking.get('tee_time', 'Not Specified')
        if tee_time_display == 'None' or tee_time_display is None or pd.isna(tee_time_display):
            tee_time_display = 'Not Specified'

        # Handle tee date display (check for NULL/NaT dates)
        tee_date = booking.get('date')
        if tee_date is None or pd.isna(tee_date):
            tee_date_display = 'Not Set'
        else:
            tee_date_display = tee_date.strftime('%b %d, %Y')

        note_content = booking.get('note', '')
        if note_content is None or pd.isna(note_content):
            note_content = 'No additional information provided'
    
        # Prepare progress bar data
        current_status = booking['status']
        if current_status == 'Pending':
            current_status = 'Inquiry'
    
        stages = [
            {'name': 'Inquiry', 'color': '#3b82f6'},
            {'name': 'Requested', 'color': '#fbbf24'},
            {'name': 'Confirmed', 'color': '#a78bfa'},
            {'name': 'Booked', 'color': '#10b981'}
        ]
    
        is_rejected = current_status == 'Rejected'
        is_cancelled = current_status == 'Cancelled'
        current_index = next((i for i, s in enumerate(stages) if s['name'] == current_status), 0)
        progress_width = (current_index / (len(stages) - 1)) * 100 if len(stages) > 1 else 0
    
        # Format requested time
        requested_time = booking['timestamp'].strftime('%b %d • %I:%M %p')
    
        with st.container():
            # Build progress bar HTML inline
            if is_rejected or is_cancelled:
                status_color = '#ef4444' if is_rejected else '#64748b'
                progress_html = f"<div style='background: #1e3a8a; padding: 1rem; border-radius: 8px; border: 2px solid #10b981;'><div style='display: flex; align-items: center; justify-content: center; gap: 0.75rem;'><div style='width: 12px; height: 12px; border-radius: 50%; background: {status_color};'></div><span style='color: {status_color}; font-weight: 700; font-size: 1rem; text-transform: uppercase; letter-spacing: 0.5px;'>{current_status}</span></div></div>"
            else:
                # Build stage nodes HTML
                stages_html = ""
                for i, stage in enumerate(stages):
                    is_active = i <= current_index
                    is_current = i == current_index
                    bg_color = stage['color'] if is_active else '#1e40af'
                    text_color = '#f9fafb' if is_active else '#64748b'
                    border_color = stage['color'] if is_current else ('#3b82f6' if is_active else '#1e40af')
                    box_shadow = '0 0 0 4px rgba(59, 130, 246, 0.4)' if is_current else 'none'
                    font_weight = '700' if is_current else '600'
    
                    stages_html += f"<div style='display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative;'><div style='width: 1.5rem; height: 1.5rem; border-radius: 50%; background: {bg_color}; border: 3px solid {border_color}; box-shadow: {box_shadow}; transition: all 0.3s ease;'></div><div style='margin-top: 0.5rem; font-size: 0.7rem; font-weight: {font_weight}; color: {text_color}; text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap;'>{stage['name']}</div></div>"
    
                progress_html = f"<div style='background: #1e3a8a; padding: 1.25rem; border-radius: 8px; border: 2px solid #10b981;'><div style='display: flex; align-items: center; justify-content: space-between; position: relative;'><div style='position: absolute; top: 0.75rem; left: 2rem; right: 2rem; height: 3px; background: #1e40af; z-index: 1;'></div><div style='position: absolute; top: 0.75rem; left: 2rem; width: calc({progress_width}% - 2rem); height: 3px; background: linear-gradient(90deg, #3b82f6, #10b981); z-index: 2;'></div>{stages_html}</div></div>"
    
            # Hotel requirement badge and dates
            hotel_required = booking.get('hotel_required', False)
            hotel_badge = ""
            hotel_dates_html = ""
    
            if hotel_required:
                hotel_badge = "<div style='display: inline-block; background: #f59e0b; color: #ffffff; padding: 0.4rem 0.8rem; border-radius: 6px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-left: 0.5rem;'>Hotel Required</div>"
    
                # Format hotel dates if available
                hotel_checkin = booking.get('hotel_checkin')
                hotel_checkout = booking.get('hotel_checkout')
    
                if hotel_checkin and not pd.isna(hotel_checkin):
                    checkin_str = hotel_checkin.strftime('%b %d, %Y')
                else:
                    checkin_str = "Not Set"
    
                if hotel_checkout and not pd.isna(hotel_checkout):
                    checkout_str = hotel_checkout.strftime('%b %d, %Y')
                else:
                    checkout_str = "Not Set"
    
                hotel_dates_html = f"<div style='background: #f59e0b; padding: 1rem; border-radius: 8px; margin-top: 1rem;'><div style='color: #ffffff; font-weight: 700; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.75rem;'>Hotel Accommodation</div><div style='display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;'><div><div style='color: #ffffff; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; margin-bottom: 0.25rem;'>Check-In</div><div style='color: #ffffff; font-size: 0.95rem; font-weight: 700;'>{checkin_str}</div></div><div><div style='color: #ffffff; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; margin-bottom: 0.25rem;'>Check-Out</div><div style='color: #ffffff; font-size: 0.95rem; font-weight: 700;'>{checkout_str}</div></div></div></div>"
    
            # Golf courses and tee times section
            golf_courses = booking.get('golf_courses', '')
            selected_tee_times = booking.get('selected_tee_times', '')
            golf_info_html = ""
    
            if golf_courses and not pd.isna(golf_courses) and str(golf_courses).strip():
                courses_list = str(golf_courses).strip()
                times_list = str(selected_tee_times).strip() if selected_tee_times and not pd.isna(selected_tee_times) else "Times not specified"
    
                golf_info_html = f"<div style='background: #10b981; padding: 1rem; border-radius: 8px; margin-top: 1rem;'><div style='color: #ffffff; font-weight: 700; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.75rem;'>Golf Courses & Tee Times</div><div style='display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;'><div><div style='color: #ffffff; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; margin-bottom: 0.25rem;'>Courses</div><div style='color: #ffffff; font-size: 0.875rem; font-weight: 600; line-height: 1.5;'>{html.escape(courses_list)}</div></div><div><div style='color: #ffffff; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; margin-bottom: 0.25rem;'>Tee Times</div><div style='color: #ffffff; font-size: 0.875rem; font-weight: 600; line-height: 1.5;'>{html.escape(times_list)}</div></div></div></div>"
    
            # Build complete card HTML including progress bar and details
            card_html = f"<div class='booking-card' style='background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; margin-bottom: 0.5rem; box-shadow: 0 4px 16px rgba(59, 130, 246, 0.3); transition: all 0.3s ease;'><div style='display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1.25rem;'><div style='flex: 1;'><div style='display: flex; align-items: center;'><div class='booking-id' style='margin-bottom: 0.5rem;'>{html.escape(str(booking['booking_id']))}</div>{hotel_badge}</div><div class='booking-email'>{html.escape(str(booking['guest_email']))}</div></div><div style='text-align: right;'><div class='timestamp'>REQUESTED</div><div class='timestamp-value'>{requested_time}</div></div></div><div style='margin-bottom: 1.5rem;'>{progress_html}</div><div style='height: 1px; background: linear-gradient(90deg, transparent, #3b82f6, transparent); margin: 1.5rem 0;'></div><div style='display: grid; grid-template-columns: repeat(4, 1fr); gap: 1.5rem; margin-bottom: 1rem;'><div><div class='data-label' style='margin-bottom: 0.5rem;'>TEE DATE</div><div style='font-size: 1rem; font-weight: 600; color: #f9fafb;'>{tee_date_display}</div></div><div><div class='data-label' style='margin-bottom: 0.5rem;'>TEE TIME</div><div style='font-size: 1rem; font-weight: 600; color: #f9fafb;'>{tee_time_display}</div></div><div><div class='data-label' style='margin-bottom: 0.5rem;'>PLAYERS</div><div style='font-size: 1rem; font-weight: 600; color: #f9fafb;'>{booking['players']}</div></div><div><div class='data-label' style='margin-bottom: 0.5rem;'>TOTAL</div><div style='font-size: 1.5rem; font-weight: 700; color: #10b981;'>€{booking['total']:,.2f}</div></div></div>{golf_info_html}{hotel_dates_html}</div>"
    
            # Render the complete card
            st.markdown(card_html, unsafe_allow_html=True)
    
            # Quick status change buttons (above the expander)
            if not is_rejected and not is_cancelled:
                st.markdown("<div style='margin: -0.5rem 0 1rem 0;'>", unsafe_allow_html=True)
                status_col1, status_col2, status_col3, status_col4, status_col5 = st.columns([1, 1, 1, 1, 2])
    
                with status_col1:
                    if booking['status'] in ['Inquiry', 'Pending']:
                        if st.button("→ Requested", key=f"quick_req_{booking['booking_id']}", use_container_width=True, help="Move to Requested"):
                            if update_booking_status(booking['booking_id'], 'Requested', st.session_state.username):
                                st.cache_data.clear()
                                st.rerun()
    
                with status_col2:
                    if booking['status'] == 'Requested':
                        if st.button("→ Confirmed", key=f"quick_conf_{booking['booking_id']}", use_container_width=True, help="Move to Confirmed"):
                            if update_booking_status(booking['booking_id'], 'Confirmed', st.session_state.username):
                                st.cache_data.clear()
                                st.rerun()
    
                with status_col3:
                    if booking['status'] == 'Confirmed':
                        if st.button("→ Booked", key=f"quick_book_{booking['booking_id']}", use_container_width=True, help="Move to Booked"):
                            if update_booking_status(booking['booking_id'], 'Booked', st.session_state.username):
                                st.cache_data.clear()
                                st.rerun()
    
                with status_col4:
                    if booking['status'] not in ['Rejected', 'Cancelled', 'Booked']:
                        if st.button("Reject", key=f"quick_rej_{booking['booking_id']}", use_container_width=True, help="Reject this booking"):
                            if update_booking_status(booking['booking_id'], 'Rejected', st.session_state.username):
                                st.cache_data.clear()
                                st.rerun()
    
                st.markdown("</div>", unsafe_allow_html=True)
    
            with st.expander("View Full Details", expanded=False):
                detail_col1, detail_col2 = st.columns([2, 1])
    
                with detail_col1:
                    st.markdown("""
                        <div style='background: #4a6278; padding: 0.75rem 1rem; border-radius: 8px 8px 0 0; border: 2px solid #6b7c3f; border-bottom: none; margin-bottom: 0;'>
                            <div style='color: #d4b896; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin: 0;'>Current Notes</div>
                        </div>
                    """, unsafe_allow_html=True)
    
                    # Editable notes text area
                    updated_note = st.text_area(
                        label="Notes",
                        value=note_content,
                        height=200,
                        disabled=False,
                        label_visibility="collapsed",
                        key=f"note_{booking['booking_id']}"
                    )
    
                    # Save notes button
                    if updated_note != note_content:
                        if st.button("Save Notes", key=f"save_note_{booking['booking_id']}", use_container_width=True):
                            if update_booking_note(booking['booking_id'], updated_note):
                                st.success("Notes saved successfully!")
                                st.cache_data.clear()
                                st.rerun()
                    
                    if booking.get('updated_by') and not pd.isna(booking.get('updated_by')):
                        st.markdown(f"""
                            <div style='margin-top: 1rem; padding: 0.75rem; background: #3d5266; border-radius: 8px; border: 2px solid #6b7c3f;'>
                                <div style='color: #d4b896; font-size: 0.7rem; font-weight: 600; text-transform: uppercase;'>Last Updated</div>
                                <div style='color: #f7f5f2; font-size: 0.875rem; margin-top: 0.25rem;'>{booking['updated_at'].strftime('%b %d, %Y • %I:%M %p')} by {booking['updated_by']}</div>
                            </div>
                        """, unsafe_allow_html=True)

                    # Display inbound emails for this booking
                    st.markdown("""
                        <div style='background: #4a6278; padding: 0.75rem 1rem; border-radius: 8px 8px 0 0; border: 2px solid #6b7c3f; border-bottom: none; margin-top: 1.5rem; margin-bottom: 0;'>
                            <div style='color: #d4b896; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin: 0;'>Inbound Emails</div>
                        </div>
                    """, unsafe_allow_html=True)

                    emails = load_emails_by_booking_id(booking['booking_id'], booking.get('guest_email'))

                    if not emails:
                        st.markdown("""
                            <div style='background: #3d5266; padding: 1rem; border: 2px solid #6b7c3f; border-top: none; border-radius: 0 0 8px 8px;'>
                                <div style='color: #94a3b8; font-size: 0.875rem; text-align: center;'>No emails found for this booking</div>
                            </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown(f"""
                            <div style='background: #3d5266; padding: 1rem; border: 2px solid #6b7c3f; border-top: none; border-radius: 0 0 8px 8px;'>
                                <div style='color: #10b981; font-size: 0.875rem; font-weight: 600; margin-bottom: 0.75rem;'>{len(emails)} email(s) found</div>
                        """, unsafe_allow_html=True)

                        for email_idx, email in enumerate(emails):
                            # Determine status color and text
                            if email.get('processed'):
                                status_color = '#10b981'
                                status_text = 'Processed'
                            elif email.get('error_message'):
                                status_color = '#ef4444'
                                status_text = 'Error'
                            else:
                                status_color = '#fbbf24'
                                status_text = 'Unprocessed'

                            # Email type color
                            email_type = email.get('email_type', 'unknown')
                            email_type_color = {
                                'inquiry': '#3b82f6',
                                'booking_request': '#8b5cf6',
                                'staff_confirmation': '#10b981',
                                'waitlist_optin': '#f59e0b',
                                'customer_reply': '#6366f1'
                            }.get(email_type, '#64748b')

                            subject = html.escape(str(email.get('subject', 'No Subject')))
                            from_email = html.escape(str(email.get('from_email', 'N/A')))
                            received_at = email.get('received_at_formatted', 'N/A')

                            st.markdown(f"""
                                <div style='background: #2d3e50; padding: 0.75rem; border-radius: 6px; margin-bottom: 0.5rem; border-left: 3px solid {status_color};'>
                                    <div style='display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.5rem;'>
                                        <div style='flex: 1;'>
                                            <div style='color: #f9fafb; font-weight: 600; font-size: 0.875rem;'>{subject}</div>
                                            <div style='color: #3b82f6; font-size: 0.75rem; margin-top: 0.25rem;'>From: {from_email}</div>
                                        </div>
                                    </div>
                                    <div style='display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;'>
                                        <div style='background: {email_type_color}20; border: 1px solid {email_type_color}; color: {email_type_color}; padding: 0.25rem 0.5rem; border-radius: 4px; font-weight: 600; font-size: 0.65rem; text-transform: uppercase;'>
                                            {email_type}
                                        </div>
                                        <div style='background: {status_color}20; border: 1px solid {status_color}; color: {status_color}; padding: 0.25rem 0.5rem; border-radius: 4px; font-weight: 600; font-size: 0.65rem; text-transform: uppercase;'>
                                            {status_text}
                                        </div>
                                        <div style='color: #64748b; font-size: 0.7rem; margin-left: auto;'>{received_at}</div>
                                    </div>
                                </div>
                            """, unsafe_allow_html=True)

                            # Show email body details (no expander since we're already inside one)
                            body_text = email.get('body_text') or 'No body text available'

                            # Show metadata
                            col_email1, col_email2 = st.columns(2)
                            with col_email1:
                                message_id = email.get('message_id') or 'N/A'
                                display_id = message_id[:30] if len(message_id) > 30 else message_id
                                st.caption(f"📧 Message ID: {display_id}...")
                            with col_email2:
                                processing_status = email.get('processing_status')
                                if processing_status:
                                    st.caption(f"📊 Status: {processing_status}")

                            # Show email body in collapsed text area
                            st.text_area(
                                "Email Body",
                                value=body_text,
                                height=100,
                                disabled=True,
                                key=f"email_body_{booking['booking_id']}_{email_idx}",
                                label_visibility="collapsed"
                            )

                            if email.get('error_message'):
                                st.error(f"⚠️ Error: {email.get('error_message')}")

                            # Add spacing between emails
                            st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)

                        st.markdown("</div>", unsafe_allow_html=True)

                with detail_col2:
                    st.markdown("### Quick Actions")

                    # Tour Operator Toggle
                    is_tour_operator = booking.get('is_tour_operator', False)
                    deposit_percentage = booking.get('deposit_percentage', DEFAULT_DEPOSIT_PERCENTAGE)

                    st.markdown("""
                        <div style='background: #1e3a8a; padding: 0.75rem; border-radius: 8px; margin-bottom: 1rem; border: 2px solid #fbbf24;'>
                            <div style='color: #fbbf24; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;'>Customer Type</div>
                        </div>
                    """, unsafe_allow_html=True)

                    tour_operator_toggle = st.checkbox(
                        f"Tour Operator (50% deposit)",
                        value=is_tour_operator,
                        key=f"tour_op_{booking['booking_id']}",
                        help="Tour Operators require 50% deposit instead of standard 20%"
                    )

                    if tour_operator_toggle != is_tour_operator:
                        if update_tour_operator_status(booking['booking_id'], tour_operator_toggle):
                            st.success(f"Updated to {'Tour Operator' if tour_operator_toggle else 'Regular Customer'}")
                            st.cache_data.clear()
                            st.rerun()

                    # Payment Status Display
                    payment_status = booking.get('payment_status', 'not_requested')
                    total_paid = booking.get('total_paid', 0.0)

                    payment_status_colors = {
                        'not_requested': '#64748b',
                        'pending': '#fbbf24',
                        'deposit_paid': '#3b82f6',
                        'fully_paid': '#10b981',
                        'failed': '#ef4444'
                    }

                    payment_status_text = {
                        'not_requested': 'Not Requested',
                        'pending': 'Payment Pending',
                        'deposit_paid': 'Deposit Paid',
                        'fully_paid': 'Fully Paid',
                        'failed': 'Payment Failed'
                    }

                    status_color = payment_status_colors.get(payment_status, '#64748b')
                    status_text = payment_status_text.get(payment_status, 'Unknown')

                    st.markdown(f"""
                        <div style='background: #1e3a8a; padding: 0.75rem; border-radius: 8px; margin-bottom: 1rem; border: 2px solid {status_color};'>
                            <div style='color: #f9fafb; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;'>Payment Status</div>
                            <div style='color: {status_color}; font-size: 1rem; font-weight: 700; margin-top: 0.5rem;'>{status_text}</div>
                            <div style='color: #ffffff; font-size: 0.875rem; margin-top: 0.5rem;'>Paid: €{total_paid:.2f} / €{booking['total']:.2f}</div>
                            <div style='color: #94a3b8; font-size: 0.75rem; margin-top: 0.25rem;'>Deposit: {deposit_percentage}%</div>
                        </div>
                    """, unsafe_allow_html=True)

                    # Request Payment Section
                    if STRIPE_SECRET_KEY:
                        st.markdown("""
                            <div style='background: #10b981; padding: 0.75rem; border-radius: 8px; margin-bottom: 1rem;'>
                                <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;'>💳 Payment Request</div>
                            </div>
                        """, unsafe_allow_html=True)

                        # Payment type selection
                        payment_type = st.radio(
                            "Payment Type",
                            ["deposit", "full"],
                            format_func=lambda x: f"Deposit ({deposit_percentage}%)" if x == "deposit" else "Full Payment",
                            key=f"payment_type_{booking['booking_id']}",
                            horizontal=True
                        )

                        # Calculate amount
                        if payment_type == "deposit":
                            payment_amount = float(booking['total']) * (deposit_percentage / 100.0)
                        else:
                            payment_amount = float(booking['total'])

                        st.markdown(f"""
                            <div style='text-align: center; padding: 0.5rem; background: #1e3a8a; border-radius: 6px; margin-bottom: 0.75rem;'>
                                <div style='color: #94a3b8; font-size: 0.75rem;'>Amount to Request</div>
                                <div style='color: #10b981; font-size: 1.5rem; font-weight: 700;'>€{payment_amount:.2f}</div>
                            </div>
                        """, unsafe_allow_html=True)

                        if st.button("📧 Send Payment Request", key=f"send_payment_{booking['booking_id']}", use_container_width=True, type="primary"):
                            try:
                                # Create Stripe payment link
                                with st.spinner("Creating payment link..."):
                                    payment_data = create_stripe_payment_link(
                                        booking_id=booking['booking_id'],
                                        amount=payment_amount,
                                        payment_type=payment_type,
                                        deposit_percentage=deposit_percentage,
                                        guest_email=booking['guest_email'],
                                        guest_name=booking.get('guest_name')
                                    )

                                # Save payment record
                                if save_payment_record(
                                    booking_id=booking['booking_id'],
                                    payment_id=payment_data['payment_id'],
                                    amount=payment_amount,
                                    payment_type=payment_type,
                                    deposit_percentage=deposit_percentage,
                                    payment_link_url=payment_data['payment_link_url'],
                                    stripe_payment_link_id=payment_data['stripe_payment_link_id'],
                                    created_by=st.session_state.username
                                ):
                                    # Send email
                                    success, message = send_payment_request_email(
                                        booking=booking,
                                        payment_link_url=payment_data['payment_link_url'],
                                        amount=payment_amount,
                                        payment_type=payment_type
                                    )

                                    if success:
                                        st.success(f"✅ Payment request sent! {message}")
                                        st.info(f"Payment link: {payment_data['payment_link_url']}")
                                        st.cache_data.clear()
                                        st.rerun()
                                    else:
                                        st.warning(f"Payment link created but email failed: {message}")
                                        st.info(f"You can manually send this link: {payment_data['payment_link_url']}")
                                else:
                                    st.error("Failed to save payment record")
                            except Exception as e:
                                st.error(f"Error: {str(e)}")

                        # Display payment history
                        payments = get_booking_payments(booking['booking_id'])
                        if payments:
                            st.markdown("""
                                <div style='margin-top: 1rem; padding: 0.75rem; background: #1e3a8a; border-radius: 8px; border: 2px solid #3b82f6;'>
                                    <div style='color: #3b82f6; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.5rem;'>Payment History</div>
                            """, unsafe_allow_html=True)

                            for payment in payments[:3]:  # Show last 3 payments
                                payment_date = payment.get('created_at')
                                if payment_date and not pd.isna(payment_date):
                                    payment_date_str = payment_date.strftime('%b %d, %Y')
                                else:
                                    payment_date_str = 'N/A'

                                st.markdown(f"""
                                    <div style='background: #2d3e50; padding: 0.5rem; border-radius: 4px; margin-bottom: 0.5rem;'>
                                        <div style='color: #ffffff; font-size: 0.75rem;'>{payment['payment_type'].capitalize()}: €{payment['amount']:.2f}</div>
                                        <div style='color: #94a3b8; font-size: 0.65rem;'>{payment_date_str} • {payment['payment_status']}</div>
                                    </div>
                                """, unsafe_allow_html=True)

                            st.markdown("</div>", unsafe_allow_html=True)
                    else:
                        st.warning("Stripe not configured. Set STRIPE_SECRET_KEY to enable payments.")

                    st.markdown("<div style='margin-top: 1.5rem; border-top: 2px solid #3b82f6; padding-top: 1rem;'></div>", unsafe_allow_html=True)

                    current_status = booking['status']

                    # Status change dropdown - allows navigation to any status
                    st.markdown("<div style='margin-bottom: 1rem;'>", unsafe_allow_html=True)
                    all_statuses = ['Inquiry', 'Requested', 'Confirmed', 'Booked', 'Rejected', 'Cancelled']
                    # Set default to current status
                    current_index = all_statuses.index(current_status) if current_status in all_statuses else 0
    
                    new_status = st.selectbox(
                        "Change Status To:",
                        all_statuses,
                        index=current_index,
                        key=f"status_select_{booking['booking_id']}"
                    )
    
                    if new_status != current_status:
                        if st.button("Update Status", key=f"update_status_{booking['booking_id']}", use_container_width=True):
                            if update_booking_status(booking['booking_id'], new_status, st.session_state.username):
                                st.success(f"Status updated to {new_status}")
                                st.cache_data.clear()
                                st.rerun()
    
                    st.markdown("</div>", unsafe_allow_html=True)
    
                    # Delete booking button (with confirmation)
                    st.markdown("<div style='margin-top: 1.5rem; border-top: 2px solid #6b7c3f; padding-top: 1rem;'></div>", unsafe_allow_html=True)
                    st.markdown("<div style='color: #cc8855; font-weight: 600; font-size: 0.875rem; margin-bottom: 0.5rem;'>Danger Zone</div>", unsafe_allow_html=True)
    
                    # Initialize session state for delete confirmation
                    if f"confirm_delete_{booking['booking_id']}" not in st.session_state:
                        st.session_state[f"confirm_delete_{booking['booking_id']}"] = False
    
                    if not st.session_state[f"confirm_delete_{booking['booking_id']}"]:
                        if st.button("Delete Booking", key=f"del_{booking['booking_id']}", use_container_width=True, type="secondary"):
                            st.session_state[f"confirm_delete_{booking['booking_id']}"] = True
                            st.rerun()
                    else:
                        st.warning("Are you sure? This action cannot be undone.")
                        col_confirm1, col_confirm2 = st.columns(2)
                        with col_confirm1:
                            if st.button("Yes, Delete", key=f"confirm_del_{booking['booking_id']}", use_container_width=True):
                                if delete_booking(booking['booking_id']):
                                    st.success("Booking deleted successfully!")
                                    st.cache_data.clear()
                                    st.session_state[f"confirm_delete_{booking['booking_id']}"] = False
                                    st.rerun()
                        with col_confirm2:
                            if st.button("Cancel", key=f"cancel_del_{booking['booking_id']}", use_container_width=True):
                                st.session_state[f"confirm_delete_{booking['booking_id']}"] = False
                                st.rerun()
    
    st.markdown("<div style='height: 2px; background: #6b7c3f; margin: 2rem 0;'></div>", unsafe_allow_html=True)
    st.markdown("#### Export Options")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("Export to Excel", use_container_width=True):
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                filtered_df.to_excel(writer, index=False, sheet_name='Bookings')
    
            st.download_button(
                label="Download Excel",
                data=output.getvalue(),
                file_name=f"bookings_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    
    with col2:
        if st.button("Export to CSV", use_container_width=True):
            csv = filtered_df.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"bookings_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
    
    with col3:
        if st.button("Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    
    with col4:
        if st.button("Fix Tee Times", use_container_width=True):
            with st.spinner("Extracting tee times from email content..."):
                updated, not_found = fix_all_tee_times(st.session_state.customer_id)
                if updated > 0:
                    st.success(f"Updated {updated} booking(s) with extracted tee times!")
                    st.cache_data.clear()
                    st.rerun()
                elif not_found > 0:
                    st.warning(f"Could not extract tee times from {not_found} booking(s)")
                else:
                    st.info("All bookings already have tee times set")

# ========================================
# REPORTS & ANALYTICS VIEW
# ========================================
elif page == "Reports & Analytics":
    st.markdown("""
        <h2 style='margin-bottom: 0.5rem;'>Reports & Analytics</h2>
        <p style='color: #ffffff; margin-bottom: 1.5rem; font-size: 0.9375rem;'>Comprehensive insights into your booking performance</p>
    """, unsafe_allow_html=True)

    # Load all bookings for analytics
    df, source = load_bookings_from_db('demo')

    if df.empty:
        st.info("No booking data available for analytics")
        st.stop()

    # Date range selector for analytics
    st.markdown("### Analysis Period")
    col_range1, col_range2 = st.columns([1, 3])

    with col_range1:
        analysis_period = st.selectbox(
            "Period",
            ["Last 7 Days", "Last 30 Days", "Last 90 Days", "Last 6 Months", "Last Year", "All Time", "Custom"],
            index=1
        )

    with col_range2:
        if analysis_period == "Last 7 Days":
            analysis_start = datetime.now() - timedelta(days=7)
            analysis_end = datetime.now()
        elif analysis_period == "Last 30 Days":
            analysis_start = datetime.now() - timedelta(days=30)
            analysis_end = datetime.now()
        elif analysis_period == "Last 90 Days":
            analysis_start = datetime.now() - timedelta(days=90)
            analysis_end = datetime.now()
        elif analysis_period == "Last 6 Months":
            analysis_start = datetime.now() - timedelta(days=180)
            analysis_end = datetime.now()
        elif analysis_period == "Last Year":
            analysis_start = datetime.now() - timedelta(days=365)
            analysis_end = datetime.now()
        elif analysis_period == "All Time":
            analysis_start = df['timestamp'].min()
            analysis_end = datetime.now()
        else:  # Custom
            custom_range = st.date_input(
                "Custom Range",
                value=(datetime.now().date() - timedelta(days=30), datetime.now().date())
            )
            if isinstance(custom_range, tuple) and len(custom_range) == 2:
                analysis_start = pd.to_datetime(custom_range[0])
                analysis_end = pd.to_datetime(custom_range[1])
            else:
                analysis_start = datetime.now() - timedelta(days=30)
                analysis_end = datetime.now()

    # Filter data by analysis period
    analysis_df = df[
        (df['timestamp'] >= pd.to_datetime(analysis_start)) &
        (df['timestamp'] <= pd.to_datetime(analysis_end))
    ].copy()

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 1.5rem 0;'></div>", unsafe_allow_html=True)

    # ========================================
    # KEY METRICS OVERVIEW
    # ========================================
    st.markdown("### Key Metrics")

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

    with metric_col1:
        total_bookings = len(analysis_df)
        st.markdown(f"""
            <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.5rem;'>Total Bookings</div>
                <div style='color: #f9fafb; font-size: 2.5rem; font-weight: 700;'>{total_bookings}</div>
            </div>
        """, unsafe_allow_html=True)

    with metric_col2:
        total_revenue = analysis_df['total'].sum()
        st.markdown(f"""
            <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.5rem;'>Total Revenue</div>
                <div style='color: #10b981; font-size: 2.5rem; font-weight: 700;'>€{total_revenue:,.0f}</div>
            </div>
        """, unsafe_allow_html=True)

    with metric_col3:
        avg_booking_value = analysis_df['total'].mean() if len(analysis_df) > 0 else 0
        st.markdown(f"""
            <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.5rem;'>Avg Booking Value</div>
                <div style='color: #f9fafb; font-size: 2.5rem; font-weight: 700;'>€{avg_booking_value:,.0f}</div>
            </div>
        """, unsafe_allow_html=True)

    with metric_col4:
        total_players = analysis_df['players'].sum()
        st.markdown(f"""
            <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.5rem;'>Total Players</div>
                <div style='color: #f9fafb; font-size: 2.5rem; font-weight: 700;'>{int(total_players)}</div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # ========================================
    # BOOKING STATUS DISTRIBUTION
    # ========================================
    col_charts1, col_charts2 = st.columns(2)

    with col_charts1:
        st.markdown("### Booking Status Distribution")
        status_counts = analysis_df['status'].value_counts()

        status_data = []
        for status, count in status_counts.items():
            percentage = (count / len(analysis_df)) * 100
            status_data.append({
                'Status': status,
                'Count': count,
                'Percentage': percentage
            })

        status_summary_df = pd.DataFrame(status_data)

        # Display as a styled table
        for _, row in status_summary_df.iterrows():
            bar_width = row['Percentage']
            st.markdown(f"""
                <div style='background: #10b981; border: 2px solid #10b981; border-radius: 8px; padding: 1rem; margin-bottom: 0.75rem;'>
                    <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;'>
                        <div style='color: #f9fafb; font-weight: 600; font-size: 1rem;'>{row['Status']}</div>
                        <div style='color: #ffffff; font-weight: 700; font-size: 1.125rem;'>{int(row['Count'])}</div>
                    </div>
                    <div style='background: #1e3a8a; border-radius: 4px; height: 8px; overflow: hidden;'>
                        <div style='background: linear-gradient(90deg, #3b82f6, #10b981); height: 100%; width: {bar_width}%;'></div>
                    </div>
                    <div style='color: #64748b; font-size: 0.75rem; margin-top: 0.25rem;'>{row['Percentage']:.1f}% of total</div>
                </div>
            """, unsafe_allow_html=True)

    with col_charts2:
        st.markdown("### Revenue by Status")
        revenue_by_status = analysis_df.groupby('status')['total'].sum().sort_values(ascending=False)

        total_rev = revenue_by_status.sum()

        for status, revenue in revenue_by_status.items():
            percentage = (revenue / total_rev) * 100 if total_rev > 0 else 0
            bar_width = percentage

            st.markdown(f"""
                <div style='background: #10b981; border: 2px solid #10b981; border-radius: 8px; padding: 1rem; margin-bottom: 0.75rem;'>
                    <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;'>
                        <div style='color: #f9fafb; font-weight: 600; font-size: 1rem;'>{status}</div>
                        <div style='color: #10b981; font-weight: 700; font-size: 1.125rem;'>€{revenue:,.0f}</div>
                    </div>
                    <div style='background: #1e3a8a; border-radius: 4px; height: 8px; overflow: hidden;'>
                        <div style='background: linear-gradient(90deg, #10b981, #3b82f6); height: 100%; width: {bar_width}%;'></div>
                    </div>
                    <div style='color: #64748b; font-size: 0.75rem; margin-top: 0.25rem;'>{percentage:.1f}% of revenue</div>
                </div>
            """, unsafe_allow_html=True)

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # ========================================
    # BOOKING TRENDS OVER TIME
    # ========================================
    st.markdown("### Booking Trends Over Time")

    # Group by date
    analysis_df['booking_date'] = analysis_df['timestamp'].dt.date
    daily_bookings = analysis_df.groupby('booking_date').agg({
        'booking_id': 'count',
        'total': 'sum',
        'players': 'sum'
    }).reset_index()
    daily_bookings.columns = ['Date', 'Bookings', 'Revenue', 'Players']

    # Create simple line chart display
    st.markdown("#### Daily Booking Volume")

    if len(daily_bookings) > 0:
        max_bookings = daily_bookings['Bookings'].max()

        for _, row in daily_bookings.tail(30).iterrows():  # Show last 30 days
            bar_width = (row['Bookings'] / max_bookings) * 100 if max_bookings > 0 else 0

            st.markdown(f"""
                <div style='display: flex; align-items: center; gap: 1rem; margin-bottom: 0.5rem;'>
                    <div style='color: #ffffff; font-weight: 600; min-width: 100px; font-size: 0.875rem;'>{row['Date']}</div>
                    <div style='flex: 1; background: #10b981; border-radius: 4px; height: 24px; overflow: hidden; border: 1px solid #10b981;'>
                        <div style='background: linear-gradient(90deg, #3b82f6, #10b981); height: 100%; width: {bar_width}%; display: flex; align-items: center; padding-left: 0.5rem;'>
                            <span style='color: #f9fafb; font-weight: 600; font-size: 0.75rem;'>{int(row['Bookings'])}</span>
                        </div>
                    </div>
                    <div style='color: #10b981; font-weight: 700; min-width: 80px; text-align: right; font-size: 0.875rem;'>€{row['Revenue']:,.0f}</div>
                </div>
            """, unsafe_allow_html=True)

    else:
        st.info("No booking trend data available")

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # ========================================
    # CONVERSION FUNNEL
    # ========================================
    st.markdown("### Booking Conversion Funnel")

    funnel_stages = [
        ('Inquiry', len(analysis_df[analysis_df['status'].isin(['Inquiry', 'Pending'])])),
        ('Requested', len(analysis_df[analysis_df['status'] == 'Requested'])),
        ('Confirmed', len(analysis_df[analysis_df['status'] == 'Confirmed'])),
        ('Booked', len(analysis_df[analysis_df['status'] == 'Booked']))
    ]

    total_funnel = sum([count for _, count in funnel_stages])

    if total_funnel > 0:
        for i, (stage, count) in enumerate(funnel_stages):
            percentage = (count / total_funnel) * 100
            bar_width = percentage

            # Calculate conversion from previous stage
            if i > 0:
                prev_count = funnel_stages[i-1][1]
                conversion = (count / prev_count) * 100 if prev_count > 0 else 0
                conversion_text = f"<div style='color: #64748b; font-size: 0.75rem; margin-top: 0.25rem;'>Conversion: {conversion:.1f}% from previous stage</div>"
            else:
                conversion_text = ""

            st.markdown(f"""
                <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 8px; padding: 1.25rem; margin-bottom: 1rem;'>
                    <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;'>
                        <div style='color: #f9fafb; font-weight: 700; font-size: 1.25rem;'>{stage}</div>
                        <div style='color: #ffffff; font-weight: 700; font-size: 1.5rem;'>{count}</div>
                    </div>
                    <div style='background: #1e3a8a; border-radius: 6px; height: 12px; overflow: hidden;'>
                        <div style='background: linear-gradient(90deg, #3b82f6, #10b981); height: 100%; width: {bar_width}%;'></div>
                    </div>
                    <div style='color: #64748b; font-size: 0.75rem; margin-top: 0.5rem;'>{percentage:.1f}% of total funnel volume</div>
                    {conversion_text}
                </div>
            """, unsafe_allow_html=True)

        # Overall conversion rate
        booked_count = funnel_stages[-1][1]
        inquiry_count = funnel_stages[0][1]
        overall_conversion = (booked_count / inquiry_count) * 100 if inquiry_count > 0 else 0

        st.markdown(f"""
            <div style='background: #3a5a40; border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center; margin-top: 1.5rem;'>
                <div style='color: #ffffff; font-size: 0.875rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.5rem;'>Overall Conversion Rate</div>
                <div style='color: #10b981; font-size: 3rem; font-weight: 700;'>{overall_conversion:.1f}%</div>
                <div style='color: #ffffff; font-size: 0.875rem; margin-top: 0.5rem;'>From Inquiry to Booked</div>
            </div>
        """, unsafe_allow_html=True)

    else:
        st.info("No funnel data available for this period")

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # ========================================
    # PEAK BOOKING TIMES
    # ========================================
    st.markdown("### Peak Booking Times")

    col_peak1, col_peak2 = st.columns(2)

    with col_peak1:
        st.markdown("#### Most Popular Tee Times")
        tee_time_popularity = analysis_df[analysis_df['tee_time'].notna()].groupby('tee_time').size().sort_values(ascending=False).head(10)

        if len(tee_time_popularity) > 0:
            max_pop = tee_time_popularity.max()

            for tee_time, count in tee_time_popularity.items():
                bar_width = (count / max_pop) * 100 if max_pop > 0 else 0

                st.markdown(f"""
                    <div style='background: #10b981; border: 1px solid #10b981; border-radius: 6px; padding: 0.75rem; margin-bottom: 0.5rem;'>
                        <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;'>
                            <div style='color: #f9fafb; font-weight: 600;'>{tee_time}</div>
                            <div style='color: #ffffff; font-weight: 700;'>{int(count)} bookings</div>
                        </div>
                        <div style='background: #1e3a8a; border-radius: 3px; height: 6px; overflow: hidden;'>
                            <div style='background: #3b82f6; height: 100%; width: {bar_width}%;'></div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No tee time data available")

    with col_peak2:
        st.markdown("#### Busiest Days of Week")
        analysis_df['day_of_week'] = pd.to_datetime(analysis_df['date']).dt.day_name()
        day_popularity = analysis_df.groupby('day_of_week').size().reindex(
            ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
            fill_value=0
        )

        if day_popularity.sum() > 0:
            max_day = day_popularity.max()

            for day, count in day_popularity.items():
                bar_width = (count / max_day) * 100 if max_day > 0 else 0

                st.markdown(f"""
                    <div style='background: #10b981; border: 1px solid #10b981; border-radius: 6px; padding: 0.75rem; margin-bottom: 0.5rem;'>
                        <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;'>
                            <div style='color: #f9fafb; font-weight: 600;'>{day}</div>
                            <div style='color: #ffffff; font-weight: 700;'>{int(count)} bookings</div>
                        </div>
                        <div style='background: #1e3a8a; border-radius: 3px; height: 6px; overflow: hidden;'>
                            <div style='background: #10b981; height: 100%; width: {bar_width}%;'></div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No day of week data available")

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # ========================================
    # LEAD TIMES ANALYTICS
    # ========================================
    st.markdown("### Average Lead Times")

    lead_times_df = calculate_lead_times(analysis_df)

    if not lead_times_df.empty:
        col_lead1, col_lead2, col_lead3 = st.columns(3)

        with col_lead1:
            avg_lead_time = lead_times_df['lead_time_days'].mean()
            st.markdown(f"""
                <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                    <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.5rem;'>Average Lead Time</div>
                    <div style='color: #f9fafb; font-size: 2.5rem; font-weight: 700;'>{avg_lead_time:.1f}</div>
                    <div style='color: #64748b; font-size: 0.875rem;'>days in advance</div>
                </div>
            """, unsafe_allow_html=True)

        with col_lead2:
            min_lead_time = lead_times_df['lead_time_days'].min()
            st.markdown(f"""
                <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                    <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.5rem;'>Minimum Lead Time</div>
                    <div style='color: #f9fafb; font-size: 2.5rem; font-weight: 700;'>{min_lead_time}</div>
                    <div style='color: #64748b; font-size: 0.875rem;'>days</div>
                </div>
            """, unsafe_allow_html=True)

        with col_lead3:
            max_lead_time = lead_times_df['lead_time_days'].max()
            st.markdown(f"""
                <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                    <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.5rem;'>Maximum Lead Time</div>
                    <div style='color: #f9fafb; font-size: 2.5rem; font-weight: 700;'>{max_lead_time}</div>
                    <div style='color: #64748b; font-size: 0.875rem;'>days</div>
                </div>
            """, unsafe_allow_html=True)

        # Lead time distribution
        st.markdown("#### Lead Time Distribution")
        lead_time_ranges = [
            ('Same Day', 0, 0),
            ('1-3 Days', 1, 3),
            ('4-7 Days', 4, 7),
            ('1-2 Weeks', 8, 14),
            ('2-4 Weeks', 15, 28),
            ('1+ Month', 29, 365)
        ]

        for label, min_days, max_days in lead_time_ranges:
            count = len(lead_times_df[(lead_times_df['lead_time_days'] >= min_days) &
                                       (lead_times_df['lead_time_days'] <= max_days)])
            percentage = (count / len(lead_times_df)) * 100 if len(lead_times_df) > 0 else 0

            st.markdown(f"""
                <div style='background: #10b981; border: 1px solid #10b981; border-radius: 6px; padding: 0.75rem; margin-bottom: 0.5rem;'>
                    <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;'>
                        <div style='color: #f9fafb; font-weight: 600;'>{label}</div>
                        <div style='color: #ffffff; font-weight: 700;'>{count} bookings ({percentage:.1f}%)</div>
                    </div>
                    <div style='background: #1e3a8a; border-radius: 3px; height: 6px; overflow: hidden;'>
                        <div style='background: linear-gradient(90deg, #3b82f6, #10b981); height: 100%; width: {percentage}%;'></div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No lead time data available for this period")

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # ========================================
    # CUSTOMER INQUIRY FREQUENCY
    # ========================================
    st.markdown("### Customer Inquiry Frequency")

    customer_freq_df = calculate_customer_inquiry_frequency(analysis_df)

    if not customer_freq_df.empty:
        # Top metrics
        col_cust1, col_cust2, col_cust3 = st.columns(3)

        with col_cust1:
            unique_customers = len(customer_freq_df)
            st.markdown(f"""
                <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                    <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase;'>Unique Customers</div>
                    <div style='color: #f9fafb; font-size: 2.5rem; font-weight: 700;'>{unique_customers}</div>
                </div>
            """, unsafe_allow_html=True)

        with col_cust2:
            avg_inquiries = customer_freq_df['Total Inquiries'].mean()
            st.markdown(f"""
                <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                    <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase;'>Avg Inquiries/Customer</div>
                    <div style='color: #f9fafb; font-size: 2.5rem; font-weight: 700;'>{avg_inquiries:.1f}</div>
                </div>
            """, unsafe_allow_html=True)

        with col_cust3:
            repeat_customers = len(customer_freq_df[customer_freq_df['Total Inquiries'] > 1])
            st.markdown(f"""
                <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                    <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase;'>Repeat Customers</div>
                    <div style='color: #f9fafb; font-size: 2.5rem; font-weight: 700;'>{repeat_customers}</div>
                </div>
            """, unsafe_allow_html=True)

        # Top customers table
        st.markdown("#### Top Customers by Inquiry Volume")
        for _, row in customer_freq_df.head(10).iterrows():
            st.markdown(f"""
                <div style='background: #10b981; border: 1px solid #10b981; border-radius: 6px; padding: 1rem; margin-bottom: 0.5rem;'>
                    <div style='display: flex; justify-content: space-between; align-items: center;'>
                        <div>
                            <div style='color: #f9fafb; font-weight: 600;'>{row['Customer Email']}</div>
                            <div style='color: #64748b; font-size: 0.75rem;'>{int(row['Completed Bookings'])} completed | {row['Conversion Rate']}% conversion</div>
                        </div>
                        <div style='text-align: right;'>
                            <div style='color: #ffffff; font-weight: 700;'>{int(row['Total Inquiries'])} inquiries</div>
                            <div style='color: #10b981; font-weight: 600;'>€{row['Total Revenue']:,.0f}</div>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No customer data available")

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # ========================================
    # GOLF COURSE POPULARITY
    # ========================================
    st.markdown("### Golf Course Popularity")

    course_popularity_df = calculate_golf_course_popularity(analysis_df)

    if not course_popularity_df.empty:
        max_requests = course_popularity_df['Total Requests'].max()

        for _, row in course_popularity_df.iterrows():
            bar_width = (row['Total Requests'] / max_requests) * 100 if max_requests > 0 else 0

            st.markdown(f"""
                <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 8px; padding: 1.25rem; margin-bottom: 1rem;'>
                    <div style='display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem;'>
                        <div>
                            <div style='color: #f9fafb; font-weight: 700; font-size: 1.125rem;'>{row['Golf Course']}</div>
                            <div style='color: #64748b; font-size: 0.875rem; margin-top: 0.25rem;'>{int(row['Confirmed Bookings'])} confirmed | {row['Conversion Rate']}% conversion</div>
                        </div>
                        <div style='text-align: right;'>
                            <div style='color: #ffffff; font-weight: 700; font-size: 1.5rem;'>{int(row['Total Requests'])}</div>
                            <div style='color: #64748b; font-size: 0.75rem;'>total requests</div>
                        </div>
                    </div>
                    <div style='background: #1e3a8a; border-radius: 6px; height: 10px; overflow: hidden; margin-bottom: 0.75rem;'>
                        <div style='background: linear-gradient(90deg, #3b82f6, #10b981); height: 100%; width: {bar_width}%;'></div>
                    </div>
                    <div style='display: flex; justify-content: space-between;'>
                        <div style='color: #64748b; font-size: 0.75rem;'>{int(row['Total Players'])} total players</div>
                        <div style='color: #10b981; font-weight: 600;'>€{row['Total Revenue']:,.0f} revenue</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No golf course data available. Ensure bookings have golf course information.")

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # ========================================
    # EXPORT ANALYTICS
    # ========================================
    st.markdown("### Export Analytics Data")

    export_col1, export_col2, export_col3 = st.columns(3)

    with export_col1:
        if st.button("Export Full Report (Excel)", use_container_width=True):
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Summary sheet
                summary_data = {
                    'Metric': ['Total Bookings', 'Total Revenue', 'Avg Booking Value', 'Total Players'],
                    'Value': [total_bookings, f"€{total_revenue:,.2f}", f"€{avg_booking_value:,.2f}", int(total_players)]
                }
                pd.DataFrame(summary_data).to_excel(writer, index=False, sheet_name='Summary')

                # Status distribution
                status_summary_df.to_excel(writer, index=False, sheet_name='Status Distribution')

                # Daily trends
                daily_bookings.to_excel(writer, index=False, sheet_name='Daily Trends')

                # Raw data
                analysis_df.to_excel(writer, index=False, sheet_name='Raw Data')

            st.download_button(
                label="Download Analytics Report",
                data=output.getvalue(),
                file_name=f"analytics_report_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

    with export_col2:
        if st.button("Export Summary (CSV)", use_container_width=True):
            summary_csv = analysis_df.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=summary_csv,
                file_name=f"analytics_summary_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )

    with export_col3:
        if st.button("Refresh Analytics", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

# ========================================
# WAITLIST VIEW
# ========================================
elif page == "Waitlist":
    st.markdown("""
        <h2 style='margin-bottom: 0.5rem;'>Tee Time Waitlist</h2>
        <p style='color: #ffffff; margin-bottom: 1.5rem; font-size: 0.9375rem;'>Manage tee time requests and notify customers of availability</p>
    """, unsafe_allow_html=True)

    # Load waitlist data
    waitlist_df = load_waitlist_from_db(st.session_state.customer_id)

    # Waitlist stats
    col_wl1, col_wl2, col_wl3, col_wl4 = st.columns(4)

    with col_wl1:
        waiting_count = len(waitlist_df[waitlist_df['status'] == 'Waiting']) if not waitlist_df.empty else 0
        st.markdown(f"""
            <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase;'>Waiting</div>
                <div style='color: #fbbf24; font-size: 2.5rem; font-weight: 700;'>{waiting_count}</div>
            </div>
        """, unsafe_allow_html=True)

    with col_wl2:
        notified_count = len(waitlist_df[waitlist_df['status'] == 'Notified']) if not waitlist_df.empty else 0
        st.markdown(f"""
            <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase;'>Notified</div>
                <div style='color: #3b82f6; font-size: 2.5rem; font-weight: 700;'>{notified_count}</div>
            </div>
        """, unsafe_allow_html=True)

    with col_wl3:
        converted_count = len(waitlist_df[waitlist_df['status'] == 'Converted']) if not waitlist_df.empty else 0
        st.markdown(f"""
            <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase;'>Converted</div>
                <div style='color: #10b981; font-size: 2.5rem; font-weight: 700;'>{converted_count}</div>
            </div>
        """, unsafe_allow_html=True)

    with col_wl4:
        expired_count = len(waitlist_df[waitlist_df['status'] == 'Expired']) if not waitlist_df.empty else 0
        st.markdown(f"""
            <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; text-align: center;'>
                <div style='color: #ffffff; font-size: 0.75rem; font-weight: 700; text-transform: uppercase;'>Expired</div>
                <div style='color: #64748b; font-size: 2.5rem; font-weight: 700;'>{expired_count}</div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # Add to Waitlist Form
    st.markdown("### Add to Waitlist")

    with st.expander("Add New Waitlist Entry", expanded=False):
        with st.form("add_waitlist_form"):
            col_form1, col_form2 = st.columns(2)

            with col_form1:
                wl_email = st.text_input("Customer Email *", key="wl_email")
                wl_name = st.text_input("Customer Name", key="wl_name")
                wl_date = st.date_input("Requested Date *", key="wl_date",
                                        min_value=datetime.now().date())
                wl_time = st.text_input("Preferred Time (e.g., 10:00 AM)", key="wl_time")

            with col_form2:
                wl_flexibility = st.selectbox("Time Flexibility",
                                              ["Flexible", "Morning Only", "Afternoon Only", "Exact Time"],
                                              key="wl_flexibility")
                wl_players = st.number_input("Number of Players", min_value=1, max_value=8, value=4, key="wl_players")
                wl_course = st.text_input("Golf Course", key="wl_course")
                wl_priority = st.slider("Priority (1=Low, 10=High)", 1, 10, 5, key="wl_priority")

            wl_notes = st.text_area("Notes", key="wl_notes", height=100)

            submit_wl = st.form_submit_button("Add to Waitlist", use_container_width=True)

            if submit_wl:
                if wl_email and wl_date:
                    success, wl_id = add_to_waitlist(
                        wl_email, wl_name, wl_date, wl_time, wl_flexibility,
                        wl_players, wl_course, wl_notes, st.session_state.customer_id, wl_priority
                    )
                    if success:
                        st.success(f"Added to waitlist: {wl_id}")
                        st.rerun()
                else:
                    st.error("Please fill in required fields (Email and Date)")

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # Waitlist Entries
    st.markdown("### Active Waitlist Entries")

    if waitlist_df.empty:
        st.info("No waitlist entries found. Add customers to the waitlist using the form above.")
    else:
        # Filter by status
        status_filter_wl = st.multiselect(
            "Filter by Status",
            ["Waiting", "Notified", "Converted", "Expired", "Cancelled"],
            default=["Waiting", "Notified"],
            key="wl_status_filter"
        )

        filtered_wl = waitlist_df[waitlist_df['status'].isin(status_filter_wl)] if status_filter_wl else waitlist_df

        for _, entry in filtered_wl.iterrows():
            status_color = {
                'Waiting': '#fbbf24',
                'Notified': '#3b82f6',
                'Converted': '#10b981',
                'Expired': '#64748b',
                'Cancelled': '#ef4444'
            }.get(entry['status'], '#64748b')

            requested_date = entry['requested_date'].strftime('%b %d, %Y') if pd.notna(entry['requested_date']) else 'N/A'
            created_at = entry['created_at'].strftime('%b %d, %Y %I:%M %p') if pd.notna(entry['created_at']) else 'N/A'

            st.markdown(f"""
                <div style='background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem;'>
                    <div style='display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem;'>
                        <div>
                            <div style='color: #f9fafb; font-weight: 700; font-size: 1rem;'>{entry['waitlist_id']}</div>
                            <div style='color: #ffffff; font-size: 0.875rem;'>{entry['guest_email']}</div>
                            {f"<div style='color: #64748b; font-size: 0.75rem;'>{entry['guest_name']}</div>" if entry.get('guest_name') else ''}
                        </div>
                        <div style='background: {status_color}20; border: 2px solid {status_color}; color: {status_color}; padding: 0.375rem 0.75rem; border-radius: 6px; font-weight: 600; font-size: 0.75rem; text-transform: uppercase;'>
                            {entry['status']}
                        </div>
                    </div>
                    <div style='display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem;'>
                        <div>
                            <div style='color: #64748b; font-size: 0.7rem; text-transform: uppercase;'>Requested Date</div>
                            <div style='color: #f9fafb; font-weight: 600;'>{requested_date}</div>
                        </div>
                        <div>
                            <div style='color: #64748b; font-size: 0.7rem; text-transform: uppercase;'>Preferred Time</div>
                            <div style='color: #f9fafb; font-weight: 600;'>{entry.get('preferred_time', 'Flexible')}</div>
                        </div>
                        <div>
                            <div style='color: #64748b; font-size: 0.7rem; text-transform: uppercase;'>Players</div>
                            <div style='color: #f9fafb; font-weight: 600;'>{entry.get('players', 1)}</div>
                        </div>
                        <div>
                            <div style='color: #64748b; font-size: 0.7rem; text-transform: uppercase;'>Priority</div>
                            <div style='color: #f9fafb; font-weight: 600;'>{entry.get('priority', 5)}/10</div>
                        </div>
                    </div>
                    <div style='margin-top: 0.75rem; color: #64748b; font-size: 0.75rem;'>
                        Added: {created_at} | Flexibility: {entry.get('time_flexibility', 'Flexible')}
                    </div>
                </div>
            """, unsafe_allow_html=True)

            # Action buttons
            if entry['status'] == 'Waiting':
                col_action1, col_action2, col_action3, col_action4 = st.columns(4)

                with col_action1:
                    if st.button("Notify Customer", key=f"notify_{entry['waitlist_id']}", use_container_width=True):
                        if update_waitlist_status(entry['waitlist_id'], 'Notified', send_notification=True):
                            st.success(f"Customer notified for {entry['waitlist_id']}")
                            st.rerun()

                with col_action2:
                    if st.button("Convert to Booking", key=f"convert_{entry['waitlist_id']}", use_container_width=True):
                        success, booking_id = convert_waitlist_to_booking(entry, entry.get('preferred_time', ''))
                        if success:
                            st.success(f"Converted to booking: {booking_id}")
                            st.cache_data.clear()
                            st.rerun()

                with col_action3:
                    if st.button("Mark Expired", key=f"expire_{entry['waitlist_id']}", use_container_width=True):
                        if update_waitlist_status(entry['waitlist_id'], 'Expired'):
                            st.rerun()

                with col_action4:
                    if st.button("Delete", key=f"delete_wl_{entry['waitlist_id']}", use_container_width=True):
                        if delete_waitlist_entry(entry['waitlist_id']):
                            st.success("Waitlist entry deleted")
                            st.rerun()

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # Check for availability matches
    st.markdown("### Find Available Slots")

    col_match1, col_match2 = st.columns(2)
    with col_match1:
        match_date = st.date_input("Check Availability for Date", key="match_date")
    with col_match2:
        if st.button("Find Matching Waitlist Entries", use_container_width=True):
            matches = get_waitlist_matches(st.session_state.customer_id, match_date)
            if not matches.empty:
                st.success(f"Found {len(matches)} matching waitlist entries for {match_date}")
                for _, match in matches.iterrows():
                    st.markdown(f"""
                        <div style='background: #10b981; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;'>
                            <div style='color: #ffffff; font-weight: 600;'>{match['guest_email']}</div>
                            <div style='color: #ffffff; font-size: 0.875rem;'>
                                {match.get('players', 1)} players | Preferred: {match.get('preferred_time', 'Flexible')} | Priority: {match.get('priority', 5)}/10
                            </div>
                        </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("No matching waitlist entries for this date")


# ========================================
# MARKETING SEGMENTATION VIEW
# ========================================
elif page == "Marketing Segmentation":
    st.markdown("""
        <h2 style='margin-bottom: 0.5rem;'>Marketing Segmentation</h2>
        <p style='color: #ffffff; margin-bottom: 1.5rem; font-size: 0.9375rem;'>Identify customer segments for targeted marketing campaigns</p>
    """, unsafe_allow_html=True)

    # Load booking data for segmentation
    df, source = load_bookings_from_db('demo')

    if df.empty:
        st.info("No booking data available for segmentation analysis")
        st.stop()

    # Calculate segments
    segments_df = identify_marketing_segments(df)

    # Segment overview
    st.markdown("### Segment Overview")

    segment_counts = segments_df['Segment'].value_counts()

    col_seg1, col_seg2, col_seg3, col_seg4, col_seg5 = st.columns(5)

    segment_colors = {
        'Frequent Non-Booker': '#ef4444',
        'Repeat Inquirer': '#f59e0b',
        'High-Value Customer': '#10b981',
        'Converted Customer': '#3b82f6',
        'Single Inquiry': '#64748b'
    }

    segments_list = ['Frequent Non-Booker', 'Repeat Inquirer', 'High-Value Customer', 'Converted Customer', 'Single Inquiry']

    for i, (col, segment) in enumerate(zip([col_seg1, col_seg2, col_seg3, col_seg4, col_seg5], segments_list)):
        count = segment_counts.get(segment, 0)
        color = segment_colors.get(segment, '#64748b')
        with col:
            st.markdown(f"""
                <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid {color}; border-radius: 12px; padding: 1rem; text-align: center;'>
                    <div style='color: {color}; font-size: 0.65rem; font-weight: 700; text-transform: uppercase; margin-bottom: 0.25rem;'>{segment}</div>
                    <div style='color: #f9fafb; font-size: 1.75rem; font-weight: 700;'>{count}</div>
                </div>
            """, unsafe_allow_html=True)

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # Frequent Non-Bookers Section (High Priority)
    st.markdown("### High Priority: Frequent Non-Bookers")
    st.markdown("<p style='color: #ffffff; margin-bottom: 1rem;'>Customers who have contacted multiple times but never completed a booking - ideal for targeted re-engagement campaigns</p>", unsafe_allow_html=True)

    non_bookers = segments_df[segments_df['Segment'] == 'Frequent Non-Booker'].sort_values('Total Contacts', ascending=False)

    if not non_bookers.empty:
        for _, customer in non_bookers.iterrows():
            last_contact = customer['Last Contact'].strftime('%b %d, %Y') if pd.notna(customer['Last Contact']) else 'N/A'

            st.markdown(f"""
                <div style='background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%); border: 2px solid #ef4444; border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem;'>
                    <div style='display: flex; justify-content: space-between; align-items: center;'>
                        <div>
                            <div style='color: #fecaca; font-weight: 700; font-size: 1rem;'>{customer['Customer Email']}</div>
                            <div style='color: #fca5a5; font-size: 0.875rem; margin-top: 0.25rem;'>
                                {int(customer['Total Contacts'])} inquiries | Last contact: {last_contact}
                            </div>
                        </div>
                        <div style='text-align: right;'>
                            <div style='background: #ef4444; color: white; padding: 0.375rem 0.75rem; border-radius: 6px; font-weight: 600; font-size: 0.75rem;'>
                                HIGH PRIORITY
                            </div>
                            <div style='color: #fca5a5; font-size: 0.75rem; margin-top: 0.5rem;'>
                                {customer['Recommended Action']}
                            </div>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No frequent non-bookers identified - great news!")

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # Repeat Inquirers (Medium Priority)
    st.markdown("### Medium Priority: Repeat Inquirers")
    st.markdown("<p style='color: #ffffff; margin-bottom: 1rem;'>Customers who have inquired twice but haven't booked - good candidates for follow-up offers</p>", unsafe_allow_html=True)

    repeat_inquirers = segments_df[segments_df['Segment'] == 'Repeat Inquirer'].sort_values('Total Contacts', ascending=False)

    if not repeat_inquirers.empty:
        for _, customer in repeat_inquirers.iterrows():
            last_contact = customer['Last Contact'].strftime('%b %d, %Y') if pd.notna(customer['Last Contact']) else 'N/A'

            st.markdown(f"""
                <div style='background: linear-gradient(135deg, #78350f 0%, #92400e 100%); border: 2px solid #f59e0b; border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem;'>
                    <div style='display: flex; justify-content: space-between; align-items: center;'>
                        <div>
                            <div style='color: #fef3c7; font-weight: 700; font-size: 1rem;'>{customer['Customer Email']}</div>
                            <div style='color: #fcd34d; font-size: 0.875rem; margin-top: 0.25rem;'>
                                {int(customer['Total Contacts'])} inquiries | Last contact: {last_contact}
                            </div>
                        </div>
                        <div style='text-align: right;'>
                            <div style='background: #f59e0b; color: #78350f; padding: 0.375rem 0.75rem; border-radius: 6px; font-weight: 600; font-size: 0.75rem;'>
                                MEDIUM PRIORITY
                            </div>
                            <div style='color: #fcd34d; font-size: 0.75rem; margin-top: 0.5rem;'>
                                {customer['Recommended Action']}
                            </div>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No repeat inquirers identified")

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # High-Value Customers (VIP)
    st.markdown("### VIP: High-Value Customers")
    st.markdown("<p style='color: #ffffff; margin-bottom: 1rem;'>Customers with completed bookings and high revenue - perfect for loyalty programs</p>", unsafe_allow_html=True)

    vip_customers = segments_df[segments_df['Segment'] == 'High-Value Customer'].sort_values('Total Revenue', ascending=False)

    if not vip_customers.empty:
        for _, customer in vip_customers.iterrows():
            last_contact = customer['Last Contact'].strftime('%b %d, %Y') if pd.notna(customer['Last Contact']) else 'N/A'

            st.markdown(f"""
                <div style='background: linear-gradient(135deg, #064e3b 0%, #065f46 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem;'>
                    <div style='display: flex; justify-content: space-between; align-items: center;'>
                        <div>
                            <div style='color: #d1fae5; font-weight: 700; font-size: 1rem;'>{customer['Customer Email']}</div>
                            <div style='color: #6ee7b7; font-size: 0.875rem; margin-top: 0.25rem;'>
                                {int(customer['Completed Bookings'])} bookings | €{customer['Total Revenue']:,.0f} total revenue
                            </div>
                        </div>
                        <div style='text-align: right;'>
                            <div style='background: #10b981; color: white; padding: 0.375rem 0.75rem; border-radius: 6px; font-weight: 600; font-size: 0.75rem;'>
                                VIP
                            </div>
                            <div style='color: #6ee7b7; font-size: 0.75rem; margin-top: 0.5rem;'>
                                {customer['Recommended Action']}
                            </div>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No high-value customers identified yet")

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # Export Segments
    st.markdown("### Export Segments")

    col_export1, col_export2, col_export3 = st.columns(3)

    with col_export1:
        if st.button("Export Non-Bookers (CSV)", use_container_width=True):
            non_bookers_export = segments_df[segments_df['Segment'].isin(['Frequent Non-Booker', 'Repeat Inquirer'])]
            csv_data = non_bookers_export.to_csv(index=False)
            st.download_button(
                label="Download Non-Bookers",
                data=csv_data,
                file_name=f"non_bookers_campaign_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )

    with col_export2:
        if st.button("Export VIP Customers (CSV)", use_container_width=True):
            vip_export = segments_df[segments_df['Segment'] == 'High-Value Customer']
            csv_data = vip_export.to_csv(index=False)
            st.download_button(
                label="Download VIP List",
                data=csv_data,
                file_name=f"vip_customers_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )

    with col_export3:
        if st.button("Export All Segments (CSV)", use_container_width=True):
            csv_data = segments_df.to_csv(index=False)
            st.download_button(
                label="Download All Segments",
                data=csv_data,
                file_name=f"all_segments_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )


# ========================================
# EMAIL AUTOMATION VIEW
# ========================================
elif page == "Email Automation":
    st.markdown("""
        <h2 style='margin-bottom: 0.5rem;'>Customer Journey Email Automation</h2>
        <p style='color: #ffffff; margin-bottom: 1.5rem; font-size: 0.9375rem;'>Automated pre-arrival and post-play email campaigns</p>
    """, unsafe_allow_html=True)

    # Configuration check
    config_status = []
    if EmailConfig.SENDGRID_API_KEY:
        config_status.append("SendGrid API Key")
    if EmailConfig.FROM_EMAIL:
        config_status.append("From Email")
    if EmailConfig.TEMPLATE_PRE_ARRIVAL:
        config_status.append("Pre-Arrival Template")
    if EmailConfig.TEMPLATE_POST_PLAY:
        config_status.append("Post-Play Template")

    if len(config_status) == 4:
        st.success(f"Email automation is configured and ready to use")
    else:
        st.warning(f"Email configuration incomplete. Set environment variables: SENDGRID_API_KEY, FROM_EMAIL, SENDGRID_TEMPLATE_PRE_ARRIVAL, SENDGRID_TEMPLATE_POST_PLAY")

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # Campaign overview
    st.markdown("### Campaign Overview")

    col_campaign1, col_campaign2 = st.columns(2)

    with col_campaign1:
        st.markdown("""
            <div style='background: linear-gradient(135deg, #059669 0%, #10b981 100%); border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem;'>
                <div style='color: #ffffff; font-weight: 700; font-size: 1.125rem; margin-bottom: 0.5rem;'>Pre-Arrival Campaign</div>
                <div style='color: #ffffff; font-size: 0.875rem; margin-bottom: 1rem;'>Welcome emails sent 3 days before play date</div>
                <div style='color: #fbbf24; font-weight: 600;'>Timing: 3 days before play</div>
            </div>
        """, unsafe_allow_html=True)

    with col_campaign2:
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%); border: 2px solid #3b82f6; border-radius: 12px; padding: 1.5rem;'>
                <div style='color: #ffffff; font-weight: 700; font-size: 1.125rem; margin-bottom: 0.5rem;'>Post-Play Campaign</div>
                <div style='color: #ffffff; font-size: 0.875rem; margin-bottom: 1rem;'>Thank you emails sent 2 days after play</div>
                <div style='color: #fbbf24; font-weight: 600;'>Timing: 2 days after play</div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # Campaign tabs
    tab1, tab2, tab3 = st.tabs(["Pre-Arrival Emails", "Post-Play Emails", "Campaign Settings"])

    with tab1:
        st.markdown("### Pre-Arrival Email Campaign")
        st.markdown("<p style='color: #ffffff; margin-bottom: 1rem;'>Send welcome emails to customers 3 days before their tee time</p>", unsafe_allow_html=True)

        # Show target date
        target_date = (datetime.now() + timedelta(days=EmailConfig.PRE_ARRIVAL_DAYS)).date()
        st.info(f"Looking for bookings with play date: {target_date.strftime('%A, %B %d, %Y')} (3 days from today)")

        # Show pending emails
        pre_arrival_bookings = get_upcoming_bookings_for_email(club_filter='demo')

        st.markdown(f"**{len(pre_arrival_bookings)} bookings** ready for pre-arrival emails")

        if len(pre_arrival_bookings) > 0:
            with st.expander("View Pending Pre-Arrival Emails", expanded=True):
                preview_df = pd.DataFrame([{
                    'Booking ID': b['booking_id'],
                    'Guest Email': clean_email_address(b['guest_email']),
                    'Guest Name': b.get('guest_name', 'N/A'),
                    'Play Date': b['play_date'],
                    'Tee Time': get_tee_time_from_booking(b),
                    'Course': b.get('golf_courses', 'N/A')
                } for b in pre_arrival_bookings[:10]])
                st.dataframe(preview_df, use_container_width=True)

                if len(pre_arrival_bookings) > 10:
                    st.info(f"Showing first 10 of {len(pre_arrival_bookings)} bookings")

        st.markdown("<div style='height: 1px; background: #3b82f6; margin: 1.5rem 0;'></div>", unsafe_allow_html=True)

        col_pre1, col_pre2 = st.columns(2)

        with col_pre1:
            if st.button("Dry Run (Preview Only)", use_container_width=True, key="pre_arrival_dry"):
                with st.spinner("Running preview..."):
                    sent, failed, results = process_pre_arrival_emails(club_filter='demo', dry_run=True)
                    st.success(f"Preview complete: {len(results)} emails would be sent")

                    if results:
                        results_df = pd.DataFrame(results)
                        st.dataframe(results_df, use_container_width=True)

        with col_pre2:
            if st.button("Send Pre-Arrival Emails", use_container_width=True, key="pre_arrival_send", type="primary"):
                if len(config_status) < 4:
                    st.error("Email configuration incomplete. Please set all required environment variables.")
                else:
                    with st.spinner("Sending pre-arrival emails..."):
                        sent, failed, results = process_pre_arrival_emails(club_filter='demo', dry_run=False)

                        if sent > 0:
                            st.success(f"Successfully sent {sent} pre-arrival emails")
                        if failed > 0:
                            st.error(f"Failed to send {failed} emails")

                        if results:
                            results_df = pd.DataFrame(results)
                            st.dataframe(results_df, use_container_width=True)

    with tab2:
        st.markdown("### Post-Play Email Campaign")
        st.markdown("<p style='color: #ffffff; margin-bottom: 1rem;'>Send thank you emails to customers 2 days after their play date</p>", unsafe_allow_html=True)

        # Show target date
        target_date_post = (datetime.now() - timedelta(days=EmailConfig.POST_PLAY_DAYS)).date()
        st.info(f"Looking for bookings with play date: {target_date_post.strftime('%A, %B %d, %Y')} (2 days ago)")

        # Show pending emails
        post_play_bookings = get_recent_bookings_for_email(club_filter='demo')

        st.markdown(f"**{len(post_play_bookings)} bookings** ready for post-play emails")

        if len(post_play_bookings) > 0:
            with st.expander("View Pending Post-Play Emails", expanded=True):
                preview_df = pd.DataFrame([{
                    'Booking ID': b['booking_id'],
                    'Guest Email': clean_email_address(b['guest_email']),
                    'Guest Name': b.get('guest_name', 'N/A'),
                    'Play Date': b['play_date'],
                    'Tee Time': get_tee_time_from_booking(b),
                    'Course': b.get('golf_courses', 'N/A')
                } for b in post_play_bookings[:10]])
                st.dataframe(preview_df, use_container_width=True)

                if len(post_play_bookings) > 10:
                    st.info(f"Showing first 10 of {len(post_play_bookings)} bookings")

        st.markdown("<div style='height: 1px; background: #3b82f6; margin: 1.5rem 0;'></div>", unsafe_allow_html=True)

        col_post1, col_post2 = st.columns(2)

        with col_post1:
            if st.button("Dry Run (Preview Only)", use_container_width=True, key="post_play_dry"):
                with st.spinner("Running preview..."):
                    sent, failed, results = process_post_play_emails(club_filter='demo', dry_run=True)
                    st.success(f"Preview complete: {len(results)} emails would be sent")

                    if results:
                        results_df = pd.DataFrame(results)
                        st.dataframe(results_df, use_container_width=True)

        with col_post2:
            if st.button("Send Post-Play Emails", use_container_width=True, key="post_play_send", type="primary"):
                if len(config_status) < 4:
                    st.error("Email configuration incomplete. Please set all required environment variables.")
                else:
                    with st.spinner("Sending post-play emails..."):
                        sent, failed, results = process_post_play_emails(club_filter='demo', dry_run=False)

                        if sent > 0:
                            st.success(f"Successfully sent {sent} post-play emails")
                        if failed > 0:
                            st.error(f"Failed to send {failed} emails")

                        if results:
                            results_df = pd.DataFrame(results)
                            st.dataframe(results_df, use_container_width=True)

    with tab3:
        st.markdown("### Campaign Settings")

        st.markdown("""
            <div style='background: #1e3a8a; border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem;'>
                <div style='color: #f9fafb; font-weight: 700; font-size: 1.125rem; margin-bottom: 1rem;'>Configuration</div>
                <div style='color: #ffffff; margin-bottom: 0.5rem;'><strong>SendGrid API Key:</strong> {}</div>
                <div style='color: #ffffff; margin-bottom: 0.5rem;'><strong>From Email:</strong> {}</div>
                <div style='color: #ffffff; margin-bottom: 0.5rem;'><strong>From Name:</strong> {}</div>
                <div style='color: #ffffff; margin-bottom: 0.5rem;'><strong>Pre-Arrival Template ID:</strong> {}</div>
                <div style='color: #ffffff; margin-bottom: 0.5rem;'><strong>Post-Play Template ID:</strong> {}</div>
            </div>
        """.format(
            "Configured" if EmailConfig.SENDGRID_API_KEY else "Not Set",
            EmailConfig.FROM_EMAIL or "Not Set",
            EmailConfig.FROM_NAME,
            EmailConfig.TEMPLATE_PRE_ARRIVAL or "Not Set",
            EmailConfig.TEMPLATE_POST_PLAY or "Not Set"
        ), unsafe_allow_html=True)

        st.markdown("""
            <div style='background: #1e3a8a; border: 2px solid #3b82f6; border-radius: 12px; padding: 1.5rem;'>
                <div style='color: #f9fafb; font-weight: 700; font-size: 1.125rem; margin-bottom: 1rem;'>Email Timing</div>
                <div style='color: #ffffff; margin-bottom: 0.5rem;'><strong>Pre-Arrival Emails:</strong> Sent {} days before play date</div>
                <div style='color: #ffffff; margin-bottom: 0.5rem;'><strong>Post-Play Emails:</strong> Sent {} days after play date</div>
            </div>
        """.format(EmailConfig.PRE_ARRIVAL_DAYS, EmailConfig.POST_PLAY_DAYS), unsafe_allow_html=True)

        st.markdown("<div style='height: 1px; background: #3b82f6; margin: 1.5rem 0;'></div>", unsafe_allow_html=True)

        st.markdown("### Database Tracking")
        st.markdown("<p style='color: #ffffff;'>To enable email tracking and prevent duplicate sends, add these columns to your bookings table:</p>", unsafe_allow_html=True)

        st.code("""
ALTER TABLE bookings ADD COLUMN pre_arrival_email_sent_at TIMESTAMP;
ALTER TABLE bookings ADD COLUMN post_play_email_sent_at TIMESTAMP;
        """, language="sql")

        st.markdown("""
            <div style='background: #1e3a8a; border: 2px solid #fbbf24; border-radius: 12px; padding: 1.5rem; margin-top: 1rem;'>
                <div style='color: #fbbf24; font-weight: 700; margin-bottom: 0.5rem;'>Note:</div>
                <div style='color: #ffffff; font-size: 0.875rem;'>The email automation will work without these columns, but emails may be sent multiple times to the same customer. Adding these tracking columns is recommended for production use.</div>
            </div>
        """, unsafe_allow_html=True)


# ========================================
# NOTIFY INTEGRATION VIEW
# ========================================
elif page == "Notify Integration":
    st.markdown("""
        <h2 style='margin-bottom: 0.5rem;'>Notify Platform Integration</h2>
        <p style='color: #ffffff; margin-bottom: 1.5rem; font-size: 0.9375rem;'>Push booking data to Notify platform via JSON, API, or CSV</p>
    """, unsafe_allow_html=True)

    # Load booking data
    df, source = load_bookings_from_db('demo')

    if df.empty:
        st.info("No booking data available for export")
        st.stop()

    # Data selection
    st.markdown("### Select Data to Export")

    col_filter1, col_filter2 = st.columns(2)

    with col_filter1:
        export_status = st.multiselect(
            "Filter by Status",
            ["Inquiry", "Requested", "Confirmed", "Booked", "Rejected", "Cancelled", "Pending"],
            default=["Booked", "Confirmed"],
            key="notify_status_filter"
        )

    with col_filter2:
        export_date_range = st.date_input(
            "Date Range",
            value=(datetime.now().date() - timedelta(days=30), datetime.now().date()),
            key="notify_date_range"
        )

    # Filter data
    export_df = df.copy()
    if export_status:
        export_df = export_df[export_df['status'].isin(export_status)]

    if isinstance(export_date_range, tuple) and len(export_date_range) == 2:
        export_df = export_df[
            (export_df['date'] >= pd.to_datetime(export_date_range[0])) &
            (export_df['date'] <= pd.to_datetime(export_date_range[1]))
        ]

    st.markdown(f"**{len(export_df)} bookings selected for export**")

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # Export Options
    st.markdown("### Export Options")

    tab1, tab2, tab3 = st.tabs(["JSON Export", "API Push", "CSV Export"])

    with tab1:
        st.markdown("#### JSON Export")
        st.markdown("<p style='color: #ffffff;'>Download booking data in JSON format for manual import to Notify platform</p>", unsafe_allow_html=True)

        if st.button("Generate JSON", use_container_width=True, key="gen_json"):
            json_data = export_to_json(export_df)
            st.code(json_data[:2000] + "..." if len(json_data) > 2000 else json_data, language="json")

            st.download_button(
                label="Download JSON File",
                data=json_data,
                file_name=f"notify_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True
            )

    with tab2:
        st.markdown("#### API Push")
        st.markdown("<p style='color: #ffffff;'>Push booking data directly to Notify platform via API</p>", unsafe_allow_html=True)

        api_endpoint = st.text_input("API Endpoint URL", placeholder="https://api.notify-platform.com/bookings",
                                      key="api_endpoint")
        api_key = st.text_input("API Key (Bearer Token)", type="password", key="api_key")

        col_api1, col_api2 = st.columns(2)

        with col_api1:
            if st.button("Test Connection", use_container_width=True, key="test_api"):
                if api_endpoint:
                    st.info("Testing connection to API endpoint...")
                    # Note: This is a mock test - in production, you'd do an actual health check
                    st.warning("Connection test simulated. Configure actual endpoint for live testing.")
                else:
                    st.error("Please enter an API endpoint URL")

        with col_api2:
            if st.button("Push to Notify", use_container_width=True, key="push_api"):
                if api_endpoint:
                    with st.spinner("Pushing data to Notify platform..."):
                        success, message = push_to_notify_api(export_df, api_endpoint, api_key)
                        if success:
                            st.success(message)
                        else:
                            st.error(message)
                else:
                    st.error("Please enter an API endpoint URL")

        # Show API payload preview
        with st.expander("Preview API Payload", expanded=False):
            api_payload = export_to_api_format(export_df)
            st.json(api_payload)

    with tab3:
        st.markdown("#### CSV Export")
        st.markdown("<p style='color: #ffffff;'>Download booking data in CSV format for spreadsheet import</p>", unsafe_allow_html=True)

        csv_data = export_notify_csv(export_df)

        st.download_button(
            label="Download CSV File",
            data=csv_data,
            file_name=f"notify_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )

        # Preview CSV data
        with st.expander("Preview CSV Data", expanded=False):
            st.dataframe(pd.read_csv(BytesIO(csv_data.encode())))

    st.markdown("<div style='height: 2px; background: #3b82f6; margin: 2rem 0;'></div>", unsafe_allow_html=True)

    # Export History (Mock)
    st.markdown("### Export Formats Reference")

    st.markdown("""
        <div style='background: #1e3a8a; border: 2px solid #10b981; border-radius: 12px; padding: 1.5rem;'>
            <div style='color: #f9fafb; font-weight: 700; font-size: 1.125rem; margin-bottom: 1rem;'>Supported Export Formats</div>
            <div style='display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.5rem;'>
                <div>
                    <div style='color: #3b82f6; font-weight: 600; margin-bottom: 0.5rem;'>JSON Format</div>
                    <div style='color: #ffffff; font-size: 0.875rem;'>Structured data with metadata, ideal for API integrations and data processing systems</div>
                </div>
                <div>
                    <div style='color: #10b981; font-weight: 600; margin-bottom: 0.5rem;'>API Push</div>
                    <div style='color: #ffffff; font-size: 0.875rem;'>Direct webhook integration with Bearer token authentication for real-time data sync</div>
                </div>
                <div>
                    <div style='color: #f59e0b; font-weight: 600; margin-bottom: 0.5rem;'>CSV Format</div>
                    <div style='color: #ffffff; font-size: 0.875rem;'>Comma-separated values for spreadsheet compatibility and bulk import tools</div>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)
