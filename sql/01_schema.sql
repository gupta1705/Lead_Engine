--SCHEME OF BASE

-- PART - 1 SEGMENTS TABLE

CREATE TABLE segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- PART - 2 ENTITIES TABLE

CREATE TABLE entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_id UUID NOT NULL REFERENCES segments(id),
    name TEXT NOT NULL,
    domain TEXT,
    source TEXT NOT NULL,
    source_url TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    fit_score NUMERIC,
    score_breakdown JSONB,
    status TEXT NOT NULL DEFAULT 'discovered'
        CHECK (status IN (
            'discovered',
            'enriched',
            'scored',
            'ready_for_review',
            'shortlisted',
            'rejected',
            'contacted',
            'in_conversation',
            'archived'
        )),
    status_reason TEXT,
    status_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- PART - 3 ENTITIES INDEXES

CREATE UNIQUE INDEX uq_entities_segment_domain
    ON entities(segment_id, domain) WHERE domain IS NOT NULL;

CREATE UNIQUE INDEX uq_entities_segment_name_nodomain
    ON entities(segment_id, lower(name)) WHERE domain IS NULL;

CREATE INDEX idx_entities_status ON entities(segment_id, status);

CREATE INDEX idx_entities_score ON entities(segment_id, fit_score DESC);

CREATE INDEX idx_entities_metadata ON entities USING gin(metadata);

-- PART - 4 CONTACTS TABLE

CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    full_name TEXT,
    role_title TEXT,
    linkedin_url TEXT,
    email TEXT,
    email_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (email_status IN (
            'unverified',
            'valid',
            'invalid',
            'catch_all',
            'unknown'
        )),
    email_verified_at TIMESTAMPTZ,
    verifier TEXT,
    source TEXT,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Multiple rows CAN share an entity_id + full_name: when the pattern oracle (Hunter) has
-- no data for a domain, Layer B writes several pattern-guess candidates for the same person
-- (same name, different email); exactly one is promoted to is_primary after verification.
CREATE INDEX idx_contacts_entity ON contacts(entity_id);

CREATE UNIQUE INDEX uq_contacts_entity_email
    ON contacts(entity_id, lower(email)) WHERE email IS NOT NULL;

-- PART 5 STAGING CANDIDATES TABLE

CREATE TABLE staging_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_id UUID NOT NULL REFERENCES segments(id),
    name TEXT NOT NULL,
    domain TEXT,
    source TEXT NOT NULL,
    source_url TEXT,
    raw JSONB NOT NULL DEFAULT '{}'::jsonb,
    imported BOOLEAN NOT NULL DEFAULT FALSE,
    import_result TEXT
        CHECK (import_result IN (
            'inserted',
            'merged_duplicate',
            'skipped_rejected'
        )),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_staging_candidate ON staging_candidates(segment_id, imported)
    WHERE imported = FALSE;

-- PART - 6 SOURCE RUNS TABLE

CREATE TABLE source_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_id UUID REFERENCES segments(id),
    source TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    candidates_found INTEGER NOT NULL DEFAULT 0,
    candidates_new INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN (
            'running',
            'succeeded',
            'failed'
        )),
    error TEXT,
    notes TEXT
);

-- PART - 7 TRIGGERS

CREATE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_segments_updated
    BEFORE UPDATE ON segments
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_entities_updated
    BEFORE UPDATE ON entities
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_contacts_updated
    BEFORE UPDATE ON contacts
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

CREATE FUNCTION set_status_changed_at() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        NEW.status_changed_at = now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_entities_status
    BEFORE UPDATE ON entities
    FOR EACH ROW
    EXECUTE FUNCTION set_status_changed_at();

-- PART - 8 ROW LEVEL SECURITY

ALTER TABLE segments           ENABLE ROW LEVEL SECURITY;
ALTER TABLE entities           ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts           ENABLE ROW LEVEL SECURITY;
ALTER TABLE staging_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_runs        ENABLE ROW LEVEL SECURITY;