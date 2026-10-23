-- =========================================================
-- Shema baze za usporedbu LLM agentnih arhitektura u e-učenju
-- Zajednička za sve 4 implementacije (LangGraph, CrewAI,
-- LlamaIndex Workflows, OpenAI Agents SDK)
-- =========================================================

-- ------------------------------------------------
-- Koncepti (redoslijed učenja bitan -> order_index)
-- ------------------------------------------------
CREATE TABLE concepts (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(50) UNIQUE NOT NULL,      -- npr. 'if_else', 'for_loop'
    name            VARCHAR(200) NOT NULL,
    order_index     INTEGER NOT NULL,
    description     TEXT
);

-- ------------------------------------------------
-- Zadaci (3 po konceptu x 4 koncepta = 12)
-- ------------------------------------------------
CREATE TABLE tasks (
    id              SERIAL PRIMARY KEY,
    concept_id      INTEGER NOT NULL REFERENCES concepts(id),
    difficulty      SMALLINT NOT NULL CHECK (difficulty IN (1, 2, 3)), -- 1=lako 2=srednje 3=teško
    title           VARCHAR(200) NOT NULL,
    prompt          TEXT NOT NULL,                    -- tekst zadatka prikazan studentu
    entry_point     VARCHAR(100) NOT NULL,
    starter_code    TEXT,                              -- opcioni template koda
    test_cases      JSONB NOT NULL,                    -- [{"input":..., "expected_output":...}, ...]
    common_errors   JSONB,                              -- [{"error_code":"off_by_one","description":"..."}]
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ------------------------------------------------
-- Simulirani profili studenata (fiksni, 3 komada)
-- ------------------------------------------------
CREATE TABLE student_profiles (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(50) UNIQUE NOT NULL,       -- 'fast_accurate', 'common_errors', 'slow_unsure'
    name            VARCHAR(200) NOT NULL,
    behavior_spec   JSONB NOT NULL                      -- parametri ponašanja simulatora
);

-- ------------------------------------------------
-- Mastery stanje studenta PO frameworku i konceptu
-- (isti profil studenta se pušta kroz sve 4 arhitekture
-- odvojeno -> zato framework_code ulazi u ključ)
-- ------------------------------------------------
CREATE TABLE student_state (
    id              SERIAL PRIMARY KEY,
    student_profile_id INTEGER NOT NULL REFERENCES student_profiles(id),
    framework_code  VARCHAR(50) NOT NULL,               -- 'langgraph','crewai','llamaindex','openai_sdk'
    concept_id      INTEGER NOT NULL REFERENCES concepts(id),
    mastery         NUMERIC(4,3) NOT NULL DEFAULT 0.0,  -- 0.0 - 1.0
    attempts        INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (student_profile_id, framework_code, concept_id)
);

-- ------------------------------------------------
-- Log svake interakcije (glavna tabela za analizu/metrike)
-- ------------------------------------------------
CREATE TABLE interaction_logs (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          UUID NOT NULL,                  -- grupira jednu punu sesiju (student x framework)
    framework_code      VARCHAR(50) NOT NULL,
    student_profile_id  INTEGER NOT NULL REFERENCES student_profiles(id),
    task_id             INTEGER NOT NULL REFERENCES tasks(id),
    step_index          INTEGER NOT NULL,               -- redni broj interakcije u sesiji

    -- ulaz/izlaz agenta
    submitted_code      TEXT,
    test_pass_count     INTEGER,
    test_total_count    INTEGER,
    is_correct          BOOLEAN,
    detected_error_code VARCHAR(50),                    -- šta je agent dijagnosticirao
    actual_error_code   VARCHAR(50),                    -- šta je zapravo simulirano (ground truth)
    agent_feedback_text TEXT,
    next_action         VARCHAR(50),                    -- 'advance','retry','easier','harder'
    mastery_before      NUMERIC(4,3),
    mastery_after       NUMERIC(4,3),

    -- metrike performansi
    llm_call_count      INTEGER NOT NULL DEFAULT 0,
    input_tokens        INTEGER,
    output_tokens        INTEGER,
    latency_ms           INTEGER,

    -- kvalitativna evaluacija (popunjava se naknadno, LLM-as-judge)
    judge_clarity_score      SMALLINT,   -- 1-5
    judge_pedagogical_score  SMALLINT,   -- 1-5
    judge_reveals_solution   BOOLEAN,

    error_occurred       BOOLEAN NOT NULL DEFAULT false,
    error_message         TEXT,

    created_at            TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_logs_framework ON interaction_logs (framework_code);
CREATE INDEX idx_logs_session ON interaction_logs (session_id);
CREATE INDEX idx_logs_task ON interaction_logs (task_id);