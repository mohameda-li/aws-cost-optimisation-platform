SET NAMES utf8mb4;
SET time_zone = '+00:00';

CREATE TABLE IF NOT EXISTS organisations (
  organisation_id INT AUTO_INCREMENT PRIMARY KEY,
  organisation_name VARCHAR(255) NOT NULL UNIQUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS customer_users (
  customer_user_id INT AUTO_INCREMENT PRIMARY KEY,
  organisation_id INT NOT NULL,
  contact_name VARCHAR(255) NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(512) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_customer_users_org
    FOREIGN KEY (organisation_id) REFERENCES organisations(organisation_id)
    ON DELETE RESTRICT
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS applications (
  application_id INT AUTO_INCREMENT PRIMARY KEY,
  customer_user_id INT NOT NULL,
  notes TEXT NULL,
  status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_applications_customer
    FOREIGN KEY (customer_user_id) REFERENCES customer_users(customer_user_id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS onboardings (
  onboarding_id INT AUTO_INCREMENT PRIMARY KEY,
  application_id INT NOT NULL UNIQUE,
  aws_region VARCHAR(32) NOT NULL DEFAULT 'eu-west-2',
  report_frequency ENUM('daily','weekly','monthly') NOT NULL DEFAULT 'weekly',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_onboardings_application
    FOREIGN KEY (application_id) REFERENCES applications(application_id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS services (
  service_code VARCHAR(32) PRIMARY KEY,
  service_name VARCHAR(128) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS onboarding_services (
  onboarding_id INT NOT NULL,
  service_code VARCHAR(32) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (onboarding_id, service_code),
  CONSTRAINT fk_onboarding_services_onboarding
    FOREIGN KEY (onboarding_id) REFERENCES onboardings(onboarding_id)
    ON DELETE CASCADE
    ON UPDATE CASCADE,
  CONSTRAINT fk_onboarding_services_service
    FOREIGN KEY (service_code) REFERENCES services(service_code)
    ON DELETE RESTRICT
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS onboarding_report_recipients (
  onboarding_id INT NOT NULL,
  report_email VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (onboarding_id, report_email),
  CONSTRAINT fk_onboarding_report_onboarding
    FOREIGN KEY (onboarding_id) REFERENCES onboardings(onboarding_id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS application_messages (
  message_id INT AUTO_INCREMENT PRIMARY KEY,
  application_id INT NOT NULL,
  customer_user_id INT NULL,
  admin_id INT NULL,
  sender_role ENUM('customer','admin') NOT NULL,
  sender_name VARCHAR(255) NOT NULL,
  message_body TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_application_messages_application
    FOREIGN KEY (application_id) REFERENCES applications(application_id)
    ON DELETE CASCADE
    ON UPDATE CASCADE,
  CONSTRAINT fk_application_messages_customer
    FOREIGN KEY (customer_user_id) REFERENCES customer_users(customer_user_id)
    ON DELETE SET NULL
    ON UPDATE CASCADE,
  CONSTRAINT fk_application_messages_admin
    FOREIGN KEY (admin_id) REFERENCES admins(admin_id)
    ON DELETE SET NULL
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS admins (
  admin_id INT AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(255) NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(512) NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  is_superuser TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
