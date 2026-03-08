-- Social Context Assistant — Initial Schema
-- Privacy architecture: face embeddings stored ONLY on-device (Android Keystore)
-- Server stores: person_id (UUID), display_name, company, interactions, follow_ups
-- No biometric data ever reaches this database.

-- contacts: people you've enrolled for recognition
CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id UUID NOT NULL,
    person_id UUID NOT NULL,
    display_name TEXT NOT NULL,
    company TEXT,
    title TEXT,
    email TEXT,
    linkedin_url TEXT,
    notes TEXT,
    tags TEXT[] DEFAULT '{}',
    relationship_strength INTEGER DEFAULT 1 CHECK (relationship_strength BETWEEN 1 AND 5),
    enrolled_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ,
    UNIQUE(owner_user_id, person_id)
);

CREATE INDEX idx_contacts_owner ON contacts(owner_user_id);
CREATE INDEX idx_contacts_person ON contacts(person_id);

-- interactions: meeting history
CREATE TABLE interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES contacts(id) ON DELETE CASCADE NOT NULL,
    owner_user_id UUID NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    venue TEXT,
    summary TEXT NOT NULL,
    topics TEXT[] DEFAULT '{}',
    sentiment TEXT DEFAULT 'neutral' CHECK (sentiment IN ('positive', 'neutral', 'negative')),
    duration_minutes INTEGER,
    source TEXT DEFAULT 'manual' CHECK (source IN ('manual', 'glasses_detected', 'plaud_transcript', 'vault_sync')),
    transcript_segment TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_interactions_contact ON interactions(contact_id);
CREATE INDEX idx_interactions_occurred ON interactions(occurred_at DESC);

-- follow_ups: commitments and action items
CREATE TABLE follow_ups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES contacts(id) ON DELETE CASCADE NOT NULL,
    owner_user_id UUID NOT NULL,
    description TEXT NOT NULL,
    due_date DATE,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'snoozed')),
    source_interaction_id UUID REFERENCES interactions(id),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_follow_ups_owner_status ON follow_ups(owner_user_id, status);
CREATE INDEX idx_follow_ups_contact ON follow_ups(contact_id);

-- enrollment_tokens: one-time QR codes for bilateral enrollment
CREATE TABLE enrollment_tokens (
    token UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL,
    display_name TEXT NOT NULL,
    company TEXT,
    title TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    used_by_user_id UUID,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_enrollment_tokens_person ON enrollment_tokens(person_id);

-- glasses_sessions: active and historical recognition sessions
CREATE TABLE glasses_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    device_fingerprint TEXT NOT NULL,
    session_token TEXT NOT NULL UNIQUE,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    recognitions_attempted INTEGER DEFAULT 0,
    recognitions_successful INTEGER DEFAULT 0
);

CREATE INDEX idx_glasses_sessions_user ON glasses_sessions(user_id);

-- recognition_events: audit log (no face data stored here)
CREATE TABLE recognition_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES glasses_sessions(id),
    user_id UUID NOT NULL,
    contact_id UUID REFERENCES contacts(id),
    recognized_at TIMESTAMPTZ DEFAULT NOW(),
    confidence FLOAT NOT NULL,
    context_served BOOLEAN DEFAULT FALSE,
    tts_script_preview TEXT  -- First 100 chars only (for audit, not full script)
);

CREATE INDEX idx_recognition_events_session ON recognition_events(session_id);
CREATE INDEX idx_recognition_events_contact ON recognition_events(contact_id);
