use std::time::Duration;

use anyhow::Context;
use sqlx::PgPool;
use sqlx::postgres::{PgConnectOptions, PgPoolOptions};

use crate::cli::DbArgs;

const SCHEMA_STATEMENTS: &[&str] = &[
    "CREATE TABLE IF NOT EXISTS shows (
        id      SERIAL PRIMARY KEY,
        station TEXT NOT NULL,
        name    TEXT NOT NULL,
        UNIQUE (station, name)
    )",
    "CREATE INDEX IF NOT EXISTS shows_station_idx ON shows (station)",
    "CREATE TABLE IF NOT EXISTS episodes (
        id        SERIAL PRIMARY KEY,
        s3_key    TEXT NOT NULL UNIQUE,
        show_id   INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
        aired_on  DATE NOT NULL,
        chapters  JSONB,
        time_slot TEXT,
        deleted   BOOLEAN NOT NULL DEFAULT FALSE
    )",
    "CREATE INDEX IF NOT EXISTS episodes_show_id_idx ON episodes (show_id)",
    "CREATE INDEX IF NOT EXISTS episodes_aired_on_idx ON episodes (aired_on)",
    "CREATE TABLE IF NOT EXISTS player_session (
        id            SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        session_token TEXT NOT NULL,
        claimed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )",
    "CREATE TABLE IF NOT EXISTS episode_play_state (
        episode_id     INTEGER PRIMARY KEY REFERENCES episodes(id) ON DELETE CASCADE,
        position_ms    BIGINT NOT NULL DEFAULT 0,
        duration_ms    BIGINT,
        last_played_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        completed      BOOLEAN NOT NULL DEFAULT FALSE
    )",
    "CREATE INDEX IF NOT EXISTS episode_play_state_recent_idx
        ON episode_play_state (last_played_at DESC)",
    "CREATE TABLE IF NOT EXISTS favorite_shows (
        show_id      INTEGER PRIMARY KEY REFERENCES shows(id) ON DELETE CASCADE,
        favorited_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )",
    "CREATE INDEX IF NOT EXISTS favorite_shows_recent_idx ON favorite_shows (favorited_at DESC)",
];

impl DbArgs {
    fn connect_options(&self) -> anyhow::Result<PgConnectOptions> {
        if let Some(url) = self.database_url.as_deref().filter(|u| !u.is_empty()) {
            return url.parse().context("invalid DATABASE_URL");
        }
        let (Some(host), Some(port), Some(user), Some(password), Some(database)) = (
            &self.postgres_host,
            self.postgres_port,
            &self.postgres_user,
            &self.postgres_password,
            &self.postgres_database,
        ) else {
            anyhow::bail!("set DATABASE_URL or all of POSTGRES_HOST/PORT/USER/PASSWORD/DATABASE");
        };
        Ok(PgConnectOptions::new()
            .host(host)
            .port(port)
            .username(user)
            .password(password)
            .database(database))
    }
}

/// Open the pool and create the schema. There is no separate migration step.
pub async fn connect(args: &DbArgs) -> anyhow::Result<PgPool> {
    let pool = PgPoolOptions::new()
        .max_connections(5)
        .acquire_timeout(Duration::from_secs(10))
        .connect_with(args.connect_options()?)
        .await
        .context("failed to connect to Postgres")?;
    bootstrap_schema(&pool).await?;
    Ok(pool)
}

async fn bootstrap_schema(pool: &PgPool) -> anyhow::Result<()> {
    let mut tx = pool.begin().await?;
    for stmt in SCHEMA_STATEMENTS {
        sqlx::query(stmt)
            .execute(&mut *tx)
            .await
            .context("failed to bootstrap schema")?;
    }
    tx.commit().await?;
    Ok(())
}
