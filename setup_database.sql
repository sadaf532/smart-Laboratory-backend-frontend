
CREATE DATABASE IF NOT EXISTS smart_lab;
USE smart_lab;



CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('admin', 'student', 'faculty') DEFAULT 'student',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS equipment (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    state ENUM('idle', 'busy', 'unavailable') DEFAULT 'idle',
    service_rate FLOAT DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS queue_entries (
    id INT AUTO_INCREMENT PRIMARY KEY,
    equipment_id INT NOT NULL,
    user_id INT NOT NULL,
    status ENUM('waiting', 'in_service', 'completed', 'cancelled') DEFAULT 'waiting',
    position_in_queue INT DEFAULT 0,
    estimated_wait FLOAT DEFAULT 0.0,
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS usage_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    equipment_id INT NOT NULL,
    user_id INT NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NULL,
    duration_minutes FLOAT DEFAULT 0.0,
    FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS state_transitions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    equipment_id INT NOT NULL,
    from_state ENUM('idle', 'busy', 'unavailable'),
    to_state ENUM('idle', 'busy', 'unavailable'),
    transitioned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    triggered_by VARCHAR(50),
    FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE CASCADE
);




INSERT INTO users (username, email, password_hash, role) VALUES
('admin', 'admin@lab.edu', 'scrypt:32768:8:1$salt$hash_placeholder', 'admin');

INSERT INTO equipment (name, category, service_rate) VALUES
('Oscilloscope - Tektronix', 'Measurement', 2.0),
('Function Generator', 'Signal', 3.0),
('Digital Multimeter', 'Measurement', 4.0),
('Soldering Station', 'Assembly', 1.5),
('Logic Analyzer', 'Digital', 2.5),
('Power Supply Unit', 'Power', 5.0),
('Spectrum Analyzer', 'RF', 1.0),
('PCB Drilling Machine', 'Fabrication', 0.8);


SELECT 'Database setup complete!' AS status;
