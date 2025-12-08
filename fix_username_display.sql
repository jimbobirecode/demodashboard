-- =====================================================
-- Fix User Full Names - Update to TeeMail Demo
-- =====================================================

BEGIN;

-- First, let's see what we have
SELECT username, full_name, customer_id FROM dashboard_users;

-- Update all users that have "Island" in their full_name
UPDATE dashboard_users
SET full_name = 'TeeMail Demo'
WHERE full_name ILIKE '%island%';

-- Alternative: Update specific users if you want to keep actual person names
-- and only change the club/organization name entries
UPDATE dashboard_users
SET full_name = 'TeeMail Demo'
WHERE full_name IN ('The Island Golf Club', 'Island Golf Club', 'island', 'Island');

-- Verify the changes
SELECT username, full_name, customer_id FROM dashboard_users;

COMMIT;

-- If you need to rollback, uncomment:
-- ROLLBACK;
