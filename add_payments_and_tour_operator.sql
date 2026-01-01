-- =====================================================
-- TeeMail Demo Payment & Tour Operator Feature Migration
-- Date: 2026-01-01
-- =====================================================

-- IMPORTANT: Back up your database before running this migration!
-- Run this script in a transaction to allow rollback if needed

BEGIN;

-- =====================================================
-- 1. CREATE PAYMENTS TABLE
-- =====================================================
-- Track all payment transactions and their status

CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    payment_id VARCHAR(100) UNIQUE NOT NULL,
    booking_id VARCHAR(50) NOT NULL,
    stripe_payment_link_id VARCHAR(255),
    stripe_checkout_session_id VARCHAR(255),
    amount DECIMAL(10, 2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'EUR',
    payment_type VARCHAR(20) NOT NULL, -- 'deposit' or 'full'
    deposit_percentage INTEGER, -- e.g., 20, 50 for Tour Operators
    payment_status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'paid', 'failed', 'expired', 'refunded'
    stripe_payment_intent_id VARCHAR(255),
    payment_link_url TEXT,
    payment_link_sent_at TIMESTAMP,
    payment_received_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(100),
    notes TEXT,
    FOREIGN KEY (booking_id) REFERENCES bookings(booking_id) ON DELETE CASCADE
);

-- Index for quick lookups
CREATE INDEX IF NOT EXISTS idx_payments_booking_id ON payments(booking_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(payment_status);
CREATE INDEX IF NOT EXISTS idx_payments_stripe_session ON payments(stripe_checkout_session_id);

-- =====================================================
-- 2. ADD TOUR OPERATOR AND PAYMENT FIELDS TO BOOKINGS
-- =====================================================

-- Add is_tour_operator flag
ALTER TABLE bookings
ADD COLUMN IF NOT EXISTS is_tour_operator BOOLEAN DEFAULT FALSE;

-- Add payment tracking fields
ALTER TABLE bookings
ADD COLUMN IF NOT EXISTS payment_status VARCHAR(20) DEFAULT 'not_requested';
-- Possible values: 'not_requested', 'pending', 'deposit_paid', 'fully_paid', 'failed'

ALTER TABLE bookings
ADD COLUMN IF NOT EXISTS deposit_percentage INTEGER DEFAULT 20;
-- Default 20% deposit, Tour Operators get 50%

ALTER TABLE bookings
ADD COLUMN IF NOT EXISTS total_paid DECIMAL(10, 2) DEFAULT 0.00;

-- =====================================================
-- 3. CREATE FUNCTION TO AUTO-UPDATE UPDATED_AT
-- =====================================================

CREATE OR REPLACE FUNCTION update_payments_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for payments table
DROP TRIGGER IF EXISTS trigger_update_payments_updated_at ON payments;
CREATE TRIGGER trigger_update_payments_updated_at
    BEFORE UPDATE ON payments
    FOR EACH ROW
    EXECUTE FUNCTION update_payments_updated_at();

-- =====================================================
-- 4. SET TOUR OPERATOR DEPOSIT PERCENTAGE
-- =====================================================

-- Update deposit percentage for any existing tour operators
UPDATE bookings
SET deposit_percentage = 50
WHERE is_tour_operator = TRUE;

-- =====================================================
-- 5. VERIFICATION
-- =====================================================

-- Verify payments table was created
SELECT 'Payments table structure' AS verification;
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'payments'
ORDER BY ordinal_position;

-- Verify bookings table was updated
SELECT 'Bookings table new columns' AS verification;
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'bookings'
AND column_name IN ('is_tour_operator', 'payment_status', 'deposit_percentage', 'total_paid')
ORDER BY column_name;

-- Count current bookings
SELECT 'Current bookings count' AS verification, COUNT(*) as total
FROM bookings;

-- =====================================================
-- COMMIT or ROLLBACK
-- =====================================================
-- If everything looks good, commit the transaction:
COMMIT;

-- If you need to rollback, uncomment the following line instead:
-- ROLLBACK;
