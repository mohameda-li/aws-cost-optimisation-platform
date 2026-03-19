SET NAMES utf8mb4;
SET time_zone = '+00:00';

INSERT INTO services (service_code, service_name) VALUES
  ('s3', 'Amazon S3'),
  ('rds', 'Amazon RDS'),
  ('ecs', 'Amazon ECS'),
  ('eks', 'Amazon EKS'),
  ('spot', 'EC2 Spot Instances')
ON DUPLICATE KEY UPDATE
  service_name = VALUES(service_name);

INSERT INTO admins (full_name, email, password_hash, is_active, is_superuser)
VALUES (
  'Admin',
  'admin@finops.local',
  'scrypt:32768:8:1$EUlhss69dncnSNqG$860b6c3dc18fd8555bba76d53270331e1d3ca663ff556671c74b17e22aafb846986acf29bc1fea08662c52e7bd184f8895cbe6fe3ea1f749c97d60f31b1f0712',
  1,
  1
)
ON DUPLICATE KEY UPDATE
  full_name = VALUES(full_name),
  password_hash = VALUES(password_hash),
  is_active = VALUES(is_active),
  is_superuser = VALUES(is_superuser);

INSERT INTO organisations (organisation_name) VALUES
  ('Northshore Retail Group'),
  ('Helix Health Services'),
  ('BrightForge Digital'),
  ('GreenSpan Logistics'),
  ('Aurelia Insights Ltd')
ON DUPLICATE KEY UPDATE
  organisation_name = VALUES(organisation_name);

INSERT INTO customer_users (organisation_id, contact_name, email, password_hash)
SELECT organisation_id, 'Sarah Ahmed', 'sarah.ahmed@northshoreretail.co.uk',
'scrypt:32768:8:1$EUlhss69dncnSNqG$860b6c3dc18fd8555bba76d53270331e1d3ca663ff556671c74b17e22aafb846986acf29bc1fea08662c52e7bd184f8895cbe6fe3ea1f749c97d60f31b1f0712'
FROM organisations WHERE organisation_name = 'Northshore Retail Group'
ON DUPLICATE KEY UPDATE contact_name = VALUES(contact_name), password_hash = VALUES(password_hash);

INSERT INTO customer_users (organisation_id, contact_name, email, password_hash)
SELECT organisation_id, 'Daniel Okoro', 'daniel.okoro@helixhealth.co.uk',
'scrypt:32768:8:1$EUlhss69dncnSNqG$860b6c3dc18fd8555bba76d53270331e1d3ca663ff556671c74b17e22aafb846986acf29bc1fea08662c52e7bd184f8895cbe6fe3ea1f749c97d60f31b1f0712'
FROM organisations WHERE organisation_name = 'Helix Health Services'
ON DUPLICATE KEY UPDATE contact_name = VALUES(contact_name), password_hash = VALUES(password_hash);

INSERT INTO customer_users (organisation_id, contact_name, email, password_hash)
SELECT organisation_id, 'Priya Kapoor', 'priya.kapoor@brightforgedigital.com',
'scrypt:32768:8:1$EUlhss69dncnSNqG$860b6c3dc18fd8555bba76d53270331e1d3ca663ff556671c74b17e22aafb846986acf29bc1fea08662c52e7bd184f8895cbe6fe3ea1f749c97d60f31b1f0712'
FROM organisations WHERE organisation_name = 'BrightForge Digital'
ON DUPLICATE KEY UPDATE contact_name = VALUES(contact_name), password_hash = VALUES(password_hash);

INSERT INTO customer_users (organisation_id, contact_name, email, password_hash)
SELECT organisation_id, 'Marcus Bennett', 'marcus.bennett@greenspanlogistics.com',
'scrypt:32768:8:1$EUlhss69dncnSNqG$860b6c3dc18fd8555bba76d53270331e1d3ca663ff556671c74b17e22aafb846986acf29bc1fea08662c52e7bd184f8895cbe6fe3ea1f749c97d60f31b1f0712'
FROM organisations WHERE organisation_name = 'GreenSpan Logistics'
ON DUPLICATE KEY UPDATE contact_name = VALUES(contact_name), password_hash = VALUES(password_hash);

INSERT INTO customer_users (organisation_id, contact_name, email, password_hash)
SELECT organisation_id, 'Layla Hassan', 'layla.hassan@aureliainsights.co.uk',
'scrypt:32768:8:1$EUlhss69dncnSNqG$860b6c3dc18fd8555bba76d53270331e1d3ca663ff556671c74b17e22aafb846986acf29bc1fea08662c52e7bd184f8895cbe6fe3ea1f749c97d60f31b1f0712'
FROM organisations WHERE organisation_name = 'Aurelia Insights Ltd'
ON DUPLICATE KEY UPDATE contact_name = VALUES(contact_name), password_hash = VALUES(password_hash);

INSERT INTO applications (customer_user_id, notes, status)
SELECT customer_user_id,
'Large retail business seeking S3 and RDS cost optimisation for archived product assets and reporting workloads.',
'approved'
FROM customer_users
WHERE email = 'sarah.ahmed@northshoreretail.co.uk'
AND NOT EXISTS (
  SELECT 1 FROM applications WHERE applications.customer_user_id = customer_users.customer_user_id
);

INSERT INTO applications (customer_user_id, notes, status)
SELECT customer_user_id,
'Healthcare organisation looking to reduce underused RDS capacity and idle ECS workloads used for internal operations.',
'approved'
FROM customer_users
WHERE email = 'daniel.okoro@helixhealth.co.uk'
AND NOT EXISTS (
  SELECT 1 FROM applications WHERE applications.customer_user_id = customer_users.customer_user_id
);

INSERT INTO applications (customer_user_id, notes, status)
SELECT customer_user_id,
'Digital agency interested in ECS and Spot recommendations before scaling client-facing services.',
'pending'
FROM customer_users
WHERE email = 'priya.kapoor@brightforgedigital.com'
AND NOT EXISTS (
  SELECT 1 FROM applications WHERE applications.customer_user_id = customer_users.customer_user_id
);

INSERT INTO applications (customer_user_id, notes, status)
SELECT customer_user_id,
'Logistics company requested EKS and S3 optimisation but application was rejected pending internal approval.',
'rejected'
FROM customer_users
WHERE email = 'marcus.bennett@greenspanlogistics.com'
AND NOT EXISTS (
  SELECT 1 FROM applications WHERE applications.customer_user_id = customer_users.customer_user_id
);

INSERT INTO applications (customer_user_id, notes, status)
SELECT customer_user_id,
'Analytics consultancy wants monthly reporting across S3, RDS and Spot usage for cloud cost visibility.',
'approved'
FROM customer_users
WHERE email = 'layla.hassan@aureliainsights.co.uk'
AND NOT EXISTS (
  SELECT 1 FROM applications WHERE applications.customer_user_id = customer_users.customer_user_id
);

INSERT INTO onboardings (application_id, aws_region, report_frequency)
SELECT a.application_id, 'eu-west-2', 'weekly'
FROM applications a
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'sarah.ahmed@northshoreretail.co.uk'
AND a.status = 'approved'
AND NOT EXISTS (
  SELECT 1 FROM onboardings o WHERE o.application_id = a.application_id
);

INSERT INTO onboardings (application_id, aws_region, report_frequency)
SELECT a.application_id, 'eu-west-1', 'weekly'
FROM applications a
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'daniel.okoro@helixhealth.co.uk'
AND a.status = 'approved'
AND NOT EXISTS (
  SELECT 1 FROM onboardings o WHERE o.application_id = a.application_id
);

INSERT INTO onboardings (application_id, aws_region, report_frequency)
SELECT a.application_id, 'eu-central-1', 'monthly'
FROM applications a
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'layla.hassan@aureliainsights.co.uk'
AND a.status = 'approved'
AND NOT EXISTS (
  SELECT 1 FROM onboardings o WHERE o.application_id = a.application_id
);

INSERT IGNORE INTO onboarding_services (onboarding_id, service_code)
SELECT o.onboarding_id, 's3'
FROM onboardings o
JOIN applications a ON a.application_id = o.application_id
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'sarah.ahmed@northshoreretail.co.uk';

INSERT IGNORE INTO onboarding_services (onboarding_id, service_code)
SELECT o.onboarding_id, 'rds'
FROM onboardings o
JOIN applications a ON a.application_id = o.application_id
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'sarah.ahmed@northshoreretail.co.uk';

INSERT IGNORE INTO onboarding_services (onboarding_id, service_code)
SELECT o.onboarding_id, 'rds'
FROM onboardings o
JOIN applications a ON a.application_id = o.application_id
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'daniel.okoro@helixhealth.co.uk';

INSERT IGNORE INTO onboarding_services (onboarding_id, service_code)
SELECT o.onboarding_id, 'ecs'
FROM onboardings o
JOIN applications a ON a.application_id = o.application_id
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'daniel.okoro@helixhealth.co.uk';

INSERT IGNORE INTO onboarding_services (onboarding_id, service_code)
SELECT o.onboarding_id, 's3'
FROM onboardings o
JOIN applications a ON a.application_id = o.application_id
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'layla.hassan@aureliainsights.co.uk';

INSERT IGNORE INTO onboarding_services (onboarding_id, service_code)
SELECT o.onboarding_id, 'rds'
FROM onboardings o
JOIN applications a ON a.application_id = o.application_id
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'layla.hassan@aureliainsights.co.uk';

INSERT IGNORE INTO onboarding_services (onboarding_id, service_code)
SELECT o.onboarding_id, 'spot'
FROM onboardings o
JOIN applications a ON a.application_id = o.application_id
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'layla.hassan@aureliainsights.co.uk';

INSERT IGNORE INTO onboarding_report_recipients (onboarding_id, report_email)
SELECT o.onboarding_id, 'finance@northshoreretail.co.uk'
FROM onboardings o
JOIN applications a ON a.application_id = o.application_id
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'sarah.ahmed@northshoreretail.co.uk';

INSERT IGNORE INTO onboarding_report_recipients (onboarding_id, report_email)
SELECT o.onboarding_id, 'ops@northshoreretail.co.uk'
FROM onboardings o
JOIN applications a ON a.application_id = o.application_id
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'sarah.ahmed@northshoreretail.co.uk';

INSERT IGNORE INTO onboarding_report_recipients (onboarding_id, report_email)
SELECT o.onboarding_id, 'cloud.operations@helixhealth.co.uk'
FROM onboardings o
JOIN applications a ON a.application_id = o.application_id
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'daniel.okoro@helixhealth.co.uk';

INSERT IGNORE INTO onboarding_report_recipients (onboarding_id, report_email)
SELECT o.onboarding_id, 'procurement@helixhealth.co.uk'
FROM onboardings o
JOIN applications a ON a.application_id = o.application_id
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'daniel.okoro@helixhealth.co.uk';

INSERT IGNORE INTO onboarding_report_recipients (onboarding_id, report_email)
SELECT o.onboarding_id, 'platform@aureliainsights.co.uk'
FROM onboardings o
JOIN applications a ON a.application_id = o.application_id
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'layla.hassan@aureliainsights.co.uk';

INSERT IGNORE INTO onboarding_report_recipients (onboarding_id, report_email)
SELECT o.onboarding_id, 'leadership@aureliainsights.co.uk'
FROM onboardings o
JOIN applications a ON a.application_id = o.application_id
JOIN customer_users cu ON cu.customer_user_id = a.customer_user_id
WHERE cu.email = 'layla.hassan@aureliainsights.co.uk';
