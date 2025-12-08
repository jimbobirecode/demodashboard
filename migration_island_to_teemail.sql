-- =====================================================
-- TeeMail Demo Database Migration Script
-- Migration: Remove Island references and replace with TeeMail Demo
-- Date: 2025-12-08
-- =====================================================

-- IMPORTANT: Back up your database before running this migration!
-- Run this script in a transaction to allow rollback if needed

BEGIN;

-- =====================================================
-- 1. UPDATE BOOKINGS TABLE
-- =====================================================
-- Update all variations of 'island' references to 'teemail' variants in bookings.club column

UPDATE bookings
SET club = 'teemail'
WHERE club = 'island';

UPDATE bookings
SET club = 'teemailclub'
WHERE club = 'islandgolfclub';

UPDATE bookings
SET club = 'teemail-demo'
WHERE club = 'island-golf-club';

UPDATE bookings
SET club = 'teemail_demo'
WHERE club = 'island_golf_club';

-- Verify bookings update
SELECT 'Bookings table updated' AS status,
       club,
       COUNT(*) as count
FROM bookings
GROUP BY club;


-- =====================================================
-- 2. UPDATE WAITLIST TABLE
-- =====================================================
-- Update all variations of 'island' references to 'teemail' variants in waitlist.club column

UPDATE waitlist
SET club = 'teemail'
WHERE club = 'island';

UPDATE waitlist
SET club = 'teemailclub'
WHERE club = 'islandgolfclub';

UPDATE waitlist
SET club = 'teemail-demo'
WHERE club = 'island-golf-club';

UPDATE waitlist
SET club = 'teemail_demo'
WHERE club = 'island_golf_club';

-- Verify waitlist update
SELECT 'Waitlist table updated' AS status,
       club,
       COUNT(*) as count
FROM waitlist
GROUP BY club;


-- =====================================================
-- 3. UPDATE DASHBOARD_USERS TABLE
-- =====================================================
-- Update customer_id column to use new teemail identifiers

UPDATE dashboard_users
SET customer_id = 'teemail'
WHERE customer_id = 'island';

UPDATE dashboard_users
SET customer_id = 'teemailclub'
WHERE customer_id = 'islandgolfclub';

UPDATE dashboard_users
SET customer_id = 'teemail-demo'
WHERE customer_id = 'island-golf-club';

UPDATE dashboard_users
SET customer_id = 'teemail_demo'
WHERE customer_id = 'island_golf_club';

-- Verify dashboard_users update
SELECT 'Dashboard users table updated' AS status,
       customer_id,
       username,
       full_name,
       COUNT(*) as count
FROM dashboard_users
GROUP BY customer_id, username, full_name;


-- =====================================================
-- 4. FINAL VERIFICATION
-- =====================================================
-- Check if any 'island' references remain (should return 0 rows)

SELECT 'Remaining island references in bookings' AS check_type, COUNT(*) as remaining_count
FROM bookings
WHERE club ILIKE '%island%';

SELECT 'Remaining island references in waitlist' AS check_type, COUNT(*) as remaining_count
FROM waitlist
WHERE club ILIKE '%island%';

SELECT 'Remaining island references in dashboard_users' AS check_type, COUNT(*) as remaining_count
FROM dashboard_users
WHERE customer_id ILIKE '%island%';


-- =====================================================
-- 5. SUMMARY OF CHANGES
-- =====================================================
SELECT 'MIGRATION SUMMARY' AS summary;
SELECT 'Old Value' as old_value, 'New Value' as new_value
UNION ALL
SELECT 'island', 'teemail'
UNION ALL
SELECT 'islandgolfclub', 'teemailclub'
UNION ALL
SELECT 'island-golf-club', 'teemail-demo'
UNION ALL
SELECT 'island_golf_club', 'teemail_demo';


-- =====================================================
-- COMMIT or ROLLBACK
-- =====================================================
-- If everything looks good, commit the transaction:
COMMIT;

-- If you need to rollback, uncomment the following line instead:
-- ROLLBACK;
