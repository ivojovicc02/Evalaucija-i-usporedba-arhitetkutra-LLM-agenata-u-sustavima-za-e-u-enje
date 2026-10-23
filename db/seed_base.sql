-- Osnovni koncepti (redoslijed učenja)
INSERT INTO concepts (code, name, order_index, description) VALUES
    ('if_else',   'Uslovi (if/else)',        1, 'Osnovna grananja logike'),
    ('for_loop',  'For petlje',               2, 'Iteracija kroz poznat broj koraka / sekvencu'),
    ('while_loop','While petlje',             3, 'Iteracija dok je uslov ispunjen'),
    ('nested',    'Ugniježđene petlje/uslovi',4, 'Kombinacija prethodna tri koncepta');

-- 3 fiksna profila simuliranih studenata
INSERT INTO student_profiles (code, name, behavior_spec) VALUES
(
    'fast_accurate',
    'Student A - brz i tačan',
    '{
        "correctness_rate": 0.9,
        "response_delay_pattern": "fast",
        "makes_typical_errors": false,
        "clarifies_when_confused": true
    }'::jsonb
),
(
    'common_errors',
    'Student B - tipične greške',
    '{
        "correctness_rate": 0.4,
        "response_delay_pattern": "normal",
        "makes_typical_errors": true,
        "error_injection_mode": "one_common_error_per_attempt",
        "clarifies_when_confused": true
    }'::jsonb
),
(
    'slow_unsure',
    'Student C - spor i nesiguran',
    '{
        "correctness_rate": 0.5,
        "response_delay_pattern": "slow",
        "makes_typical_errors": true,
        "gives_short_unclear_answers": true,
        "clarifies_when_confused": false,
        "max_attempts_before_giveup": 4
    }'::jsonb
);