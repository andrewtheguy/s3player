//! End-to-end tests: the real `s3player` binary (`index`, `server`) against a
//! live S3 (Silo) and Postgres. Ignored by default; `scripts/e2e.sh` starts
//! both servers and runs them with the `S3PLAYER_E2E_*` environment set.
//!
//! Every test gets its own bucket and database, so tests run in parallel.

use std::net::TcpListener;
use std::path::Path;
use std::process::{Child, Command, Output, Stdio};
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::{Duration, Instant};

use aws_sdk_s3::primitives::ByteStream;
use rand::Rng;
use reqwest::StatusCode;
use reqwest::header::{self, HeaderMap};
use serde_json::{Value, json};
use sqlx::postgres::{PgConnectOptions, PgPoolOptions};
use sqlx::{ConnectOptions, PgPool};

const PASSWORD: &str = "e2e-password";
const STATION: &str = "rthk-radio1";

fn env(name: &str) -> String {
    std::env::var(name).unwrap_or_else(|_| panic!("{name} is not set; run the e2e suite via scripts/e2e.sh"))
}

struct Services {
    s3_endpoint: String,
    s3_access_key_id: String,
    s3_secret_access_key: String,
    s3_region: String,
    admin_db: PgConnectOptions,
}

impl Services {
    fn from_env() -> Self {
        Self {
            s3_endpoint: env("S3PLAYER_E2E_S3_ENDPOINT"),
            s3_access_key_id: env("S3PLAYER_E2E_S3_ACCESS_KEY_ID"),
            s3_secret_access_key: env("S3PLAYER_E2E_S3_SECRET_ACCESS_KEY"),
            s3_region: env("S3PLAYER_E2E_S3_REGION"),
            admin_db: env("S3PLAYER_E2E_DATABASE_URL").parse().expect("S3PLAYER_E2E_DATABASE_URL"),
        }
    }
}

/// A fresh bucket and database plus clients for seeding and asserting.
struct Fixture {
    services: Services,
    bucket: String,
    database: String,
    database_url: String,
    s3: aws_sdk_s3::Client,
    /// Pool on the fixture's database, opened after the binary created the schema.
    pool: Option<PgPool>,
}

impl Fixture {
    async fn new() -> Self {
        static COUNTER: AtomicU32 = AtomicU32::new(0);
        let services = Services::from_env();
        let suffix = format!(
            "{}-{}-{:06x}",
            std::process::id(),
            COUNTER.fetch_add(1, Ordering::Relaxed),
            rand::rng().random_range(0..0xFF_FFFF)
        );
        let bucket = format!("s3player-e2e-{suffix}");
        let database = format!("s3player_e2e_{}", suffix.replace('-', "_"));

        let mut admin = services.admin_db.connect().await.expect("connect admin database");
        sqlx::query(&format!("CREATE DATABASE {database}"))
            .execute(&mut admin)
            .await
            .expect("create database");
        let database_url = services.admin_db.clone().database(&database).to_url_lossy().to_string();

        let config = aws_sdk_s3::Config::builder()
            .behavior_version(aws_sdk_s3::config::BehaviorVersion::latest())
            .region(aws_sdk_s3::config::Region::new(services.s3_region.clone()))
            .endpoint_url(&services.s3_endpoint)
            .credentials_provider(aws_sdk_s3::config::Credentials::new(
                &services.s3_access_key_id,
                &services.s3_secret_access_key,
                None,
                None,
                "e2e",
            ))
            .force_path_style(true)
            .build();
        let s3 = aws_sdk_s3::Client::from_conf(config);
        s3.create_bucket().bucket(&bucket).send().await.expect("create bucket");

        Self {
            services,
            bucket,
            database,
            database_url,
            s3,
            pool: None,
        }
    }

    /// Drop the database and empty and delete the bucket. Not a `Drop`: a
    /// failed test keeps its state for inspection.
    async fn cleanup(mut self) {
        if let Some(pool) = self.pool.take() {
            pool.close().await;
        }
        let mut admin = self.services.admin_db.connect().await.expect("connect admin database");
        sqlx::query(&format!("DROP DATABASE IF EXISTS {} WITH (FORCE)", self.database))
            .execute(&mut admin)
            .await
            .expect("drop database");
        for key in self.keys("").await {
            self.delete(&key).await;
        }
        self.s3.delete_bucket().bucket(&self.bucket).send().await.expect("delete bucket");
    }

    async fn pool(&mut self) -> PgPool {
        if self.pool.is_none() {
            let pool = PgPoolOptions::new()
                .max_connections(2)
                .connect(&self.database_url)
                .await
                .expect("connect fixture database");
            self.pool = Some(pool);
        }
        self.pool.clone().unwrap()
    }

    async fn put(&self, key: &str, body: impl Into<Vec<u8>>) {
        self.s3
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .body(ByteStream::from(body.into()))
            .send()
            .await
            .unwrap_or_else(|e| panic!("put {key}: {e:?}"));
    }

    async fn put_json(&self, key: &str, value: &Value) {
        self.put(key, serde_json::to_vec(value).unwrap()).await;
    }

    async fn delete(&self, key: &str) {
        self.s3
            .delete_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .unwrap_or_else(|e| panic!("delete {key}: {e:?}"));
    }

    async fn keys(&self, prefix: &str) -> Vec<String> {
        let mut pages = self
            .s3
            .list_objects_v2()
            .bucket(&self.bucket)
            .prefix(prefix)
            .into_paginator()
            .send();
        let mut keys = Vec::new();
        while let Some(page) = pages.next().await {
            let page = page.expect("list objects");
            keys.extend(page.contents().iter().filter_map(|o| o.key().map(str::to_string)));
        }
        keys
    }

    /// An episode's audio plus its sidecar.
    async fn put_episode(&self, audio_key: &str, audio: &[u8], sidecar: &Value) {
        self.put(audio_key, audio.to_vec()).await;
        self.put_json(&format!("{audio_key}.metadata.json"), sidecar).await;
    }

    /// `s3player` with this fixture's settings, run outside the repo so a
    /// developer's `.env` is not picked up.
    fn command(&self, args: &[&str]) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_s3player"));
        command
            .args(args)
            .current_dir(env!("CARGO_TARGET_TMPDIR"))
            .env_clear()
            .env("PATH", std::env::var("PATH").unwrap_or_default())
            .env("RUST_LOG", "info")
            .env("S3_ENDPOINT", &self.services.s3_endpoint)
            .env("S3_BUCKET", &self.bucket)
            .env("S3_REGION", &self.services.s3_region)
            .env("S3_ACCESS_KEY_ID", &self.services.s3_access_key_id)
            .env("S3_SECRET_ACCESS_KEY", &self.services.s3_secret_access_key)
            .env("DATABASE_URL", &self.database_url);
        // Keep `cargo llvm-cov` (scripts/e2e.sh --coverage) collecting from the binary.
        if let Ok(profile) = std::env::var("LLVM_PROFILE_FILE") {
            command.env("LLVM_PROFILE_FILE", profile);
        }
        command
    }

    /// Run `s3player index`, assert success, and return the stats of its
    /// closing `done:` log line.
    fn index(&self, overwrite: bool) -> IndexStats {
        let mut args = vec!["index"];
        if overwrite {
            args.push("--overwrite");
        }
        let output = self.command(&args).output().expect("run s3player index");
        assert!(output.status.success(), "index failed:\n{}", stderr(&output));
        IndexStats::parse(&stderr(&output))
    }

    fn server(&self) -> Server {
        Server::start(self.command(&["server"]))
    }
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

/// The `key=value` pairs of the indexer's closing `done:` log line.
struct IndexStats(Vec<(String, String)>);

impl IndexStats {
    fn parse(log: &str) -> Self {
        let line = log
            .lines()
            .find_map(|l| l.split_once("done: ").map(|(_, rest)| rest.to_string()))
            .unwrap_or_else(|| panic!("no `done:` line in index output:\n{log}"));
        Self(
            line.split_whitespace()
                .filter_map(|kv| kv.split_once('='))
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
        )
    }

    fn get(&self, key: &str) -> u64 {
        self.0
            .iter()
            .find(|(k, _)| k == key)
            .unwrap_or_else(|| panic!("no {key} in index stats"))
            .1
            .parse()
            .unwrap()
    }

    /// Assert the listed counters; every other numeric counter must be 0.
    fn assert(&self, expected: &[(&str, u64)]) {
        for (key, value) in &self.0 {
            if key == "overwrite" {
                continue;
            }
            let want = expected.iter().find(|(k, _)| k == key).map_or(0, |(_, v)| *v);
            assert_eq!(value.parse::<u64>().unwrap(), want, "index stat {key}");
        }
        for (key, _) in expected {
            self.get(key);
        }
    }
}

/// A running `s3player server`, killed on drop.
struct Server {
    child: Child,
    base: String,
    http: reqwest::Client,
    token: String,
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port()
}

impl Server {
    fn start(mut command: Command) -> Self {
        let port = free_port();
        let child = command
            .env("SERVER_HOST", "127.0.0.1")
            .env("SERVER_PORT", port.to_string())
            .env("SITE_PASSWORD", PASSWORD)
            .env("RUST_LOG", "warn")
            .stdout(Stdio::null())
            .stderr(Stdio::inherit())
            .spawn()
            .expect("spawn s3player server");
        let http = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .unwrap();
        Self {
            child,
            base: format!("http://127.0.0.1:{port}"),
            http,
            token: String::new(),
        }
    }

    /// Wait for the listener, then log in for a bearer token.
    async fn ready(mut self) -> Self {
        let deadline = Instant::now() + Duration::from_secs(30);
        loop {
            if let Some(status) = self.child.try_wait().unwrap() {
                panic!("server exited early: {status}");
            }
            if self.http.get(self.url("/login")).send().await.is_ok() {
                break;
            }
            assert!(Instant::now() < deadline, "server did not start listening");
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        let response = self
            .http
            .post(self.url("/api/auth/login"))
            .json(&json!({ "password": PASSWORD }))
            .send()
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        self.token = response.json::<Value>().await.unwrap()["token"].as_str().unwrap().to_string();
        self
    }

    fn url(&self, path: &str) -> String {
        format!("{}{path}", self.base)
    }

    fn get(&self, path: &str) -> reqwest::RequestBuilder {
        self.http.get(self.url(path)).bearer_auth(&self.token)
    }

    fn post(&self, path: &str) -> reqwest::RequestBuilder {
        self.http.post(self.url(path)).bearer_auth(&self.token)
    }

    fn delete(&self, path: &str) -> reqwest::RequestBuilder {
        self.http.delete(self.url(path)).bearer_auth(&self.token)
    }

    /// Authenticated GET → (status, JSON body).
    fn get_json(&self, path: &str) -> impl Future<Output = (StatusCode, Value)> + use<> {
        send_json(self.get(path))
    }

    /// SIGTERM, then the exit status once the server has shut down.
    fn terminate(&mut self) -> Option<std::process::ExitStatus> {
        if let Some(status) = self.child.try_wait().unwrap() {
            return Some(status);
        }
        Command::new("kill")
            .args(["-TERM", &self.child.id().to_string()])
            .status()
            .expect("run kill");
        let deadline = Instant::now() + Duration::from_secs(10);
        while Instant::now() < deadline {
            if let Some(status) = self.child.try_wait().unwrap() {
                return Some(status);
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        None
    }
}

impl Drop for Server {
    /// Graceful first, so an instrumented binary still writes its coverage.
    fn drop(&mut self) {
        if self.terminate().is_none() {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}

async fn send_json(request: reqwest::RequestBuilder) -> (StatusCode, Value) {
    let response = request.send().await.unwrap();
    let status = response.status();
    let body = response.text().await.unwrap();
    let value = serde_json::from_str(&body).unwrap_or_else(|_| panic!("non-JSON body ({status}): {body}"));
    (status, value)
}

fn sidecar(name: &str, date: &str, start: &str, end: &str, chapters: Option<Value>) -> Value {
    let mut meta = json!({ "show": { "name": name, "date": date, "start": start, "end": end } });
    if let Some(chapters) = chapters {
        meta["chapters"] = chapters;
    }
    meta
}

fn chapters(titles: &[&str]) -> Value {
    Value::Array(
        titles
            .iter()
            .enumerate()
            .map(|(i, title)| {
                let i = i as i64;
                json!({ "index": i, "title": title, "start_ms_in_show": i * 1000, "end_ms_in_show": (i + 1) * 1000 })
            })
            .collect(),
    )
}

fn audio_bytes(len: usize) -> Vec<u8> {
    (0..len).map(|i| (i % 251) as u8).collect()
}

fn key(station: &str, date: &str, file: &str) -> String {
    let (y, rest) = date.split_at(4);
    let (m, d) = (&rest[1..3], &rest[4..6]);
    format!("shows/{station}/{y}/{m}/{d}/{file}")
}

/// Two shows on one station and one on a second station.
async fn seed_catalog(fx: &Fixture) {
    let audio = audio_bytes(1000);
    fx.put_episode(
        &key(STATION, "2026-03-22", "morning_a.m4a"),
        &audio,
        &sidecar("Morning", "2026-03-22", "06:00", "07:00", Some(chapters(&["one", "two"]))),
    )
    .await;
    fx.put_episode(
        &key(STATION, "2026-04-05", "morning_b.m4a"),
        &audio,
        &sidecar("Morning", "2026-04-05", "06:00", "07:00", None),
    )
    .await;
    fx.put_episode(
        &key(STATION, "2026-04-06", "evening.ogg"),
        &audio,
        &sidecar("Evening", "2026-04-06", "18:00", "19:00", Some(json!([]))),
    )
    .await;
    fx.put_episode(
        &key("rthk-radio2", "2026-04-01", "talk.m4a"),
        &audio,
        &sidecar("Talk", "2026-04-01", "bad", "07:00", None),
    )
    .await;
}

async fn episode_id(pool: &PgPool, s3_key: &str) -> i32 {
    sqlx::query_scalar("SELECT id FROM episodes WHERE s3_key = $1")
        .bind(s3_key)
        .fetch_one(pool)
        .await
        .unwrap()
}

async fn show_id(pool: &PgPool, station: &str, name: &str) -> i32 {
    sqlx::query_scalar("SELECT id FROM shows WHERE station = $1 AND name = $2")
        .bind(station)
        .bind(name)
        .fetch_one(pool)
        .await
        .unwrap()
}

#[tokio::test]
#[ignore = "needs Silo and Postgres: run scripts/e2e.sh"]
async fn indexer_skips_bad_sidecars_and_tracks_changes() {
    let mut fx = Fixture::new().await;
    let audio = audio_bytes(10);
    let with_chapters = key(STATION, "2026-03-22", "a.m4a");
    let without_chapters = key(STATION, "2026-03-23", "b.m4a");
    fx.put_episode(
        &with_chapters,
        &audio,
        &sidecar("Show", "2026-03-22", "06:00", "07:00", Some(chapters(&["one", "two"]))),
    )
    .await;
    fx.put_episode(&without_chapters, &audio, &sidecar("Show", "2026-03-23", "6:00", "07:00", None))
        .await;
    // Skipped: sidecar without audio, invalid JSON, non-object JSON, no
    // show.date, bad date, no show object; plus audio/other files that are
    // not sidecars at all.
    fx.put_json(&format!("{}.metadata.json", key(STATION, "2026-03-24", "orphan.m4a")), &json!({}))
        .await;
    for (file, body) in [
        ("invalid.m4a", b"{not json".to_vec()),
        ("array.m4a", b"[1, 2]".to_vec()),
        ("nodate.m4a", serde_json::to_vec(&json!({ "show": { "name": "Show" } })).unwrap()),
        (
            "baddate.m4a",
            serde_json::to_vec(&json!({ "show": { "name": "Show", "date": "2026/03/25" } })).unwrap(),
        ),
        ("noshow.m4a", serde_json::to_vec(&json!({ "chapters": [] })).unwrap()),
    ] {
        let audio_key = key(STATION, "2026-03-25", file);
        fx.put(&audio_key, audio.clone()).await;
        fx.put(&format!("{audio_key}.metadata.json"), body).await;
    }
    fx.put(&key(STATION, "2026-03-25", "notes.txt"), "x").await;

    let stats = fx.index(false);
    stats.assert(&[
        ("scanned", 16),
        ("skipped_non_metadata", 8),
        ("skipped_missing_audio", 1),
        ("skipped_invalid_metadata", 4),
        ("skipped_missing_show_date", 1),
        ("inserted", 2),
        ("chapters_filled", 1),
    ]);

    let pool = fx.pool().await;
    type Row = (String, String, chrono::NaiveDate, Option<String>, Option<Value>, bool);
    let rows: Vec<Row> = sqlx::query_as(
        "SELECT e.s3_key, s.name, e.aired_on, e.time_slot, e.chapters, e.deleted
         FROM episodes e JOIN shows s ON s.id = e.show_id ORDER BY e.s3_key",
    )
    .fetch_all(&pool)
    .await
    .unwrap();
    let date = |s: &str| chrono::NaiveDate::parse_from_str(s, "%Y-%m-%d").unwrap();
    assert_eq!(
        rows,
        vec![
            (
                with_chapters.clone(),
                "Show".to_string(),
                date("2026-03-22"),
                Some("0600_0700".to_string()),
                Some(json!([
                    { "title": "one", "start": 0, "end": 1000 },
                    { "title": "two", "start": 1000, "end": 2000 },
                ])),
                false,
            ),
            (without_chapters.clone(), "Show".to_string(), date("2026-03-23"), None, None, false),
        ]
    );

    // Re-running without --overwrite leaves existing rows alone.
    fx.put_json(
        &format!("{with_chapters}.metadata.json"),
        &sidecar("Renamed", "2026-03-21", "08:00", "09:00", None),
    )
    .await;
    fx.put_json(
        &format!("{without_chapters}.metadata.json"),
        &sidecar("Show", "2026-03-23", "06:00", "07:00", Some(chapters(&["new"]))),
    )
    .await;
    let stats = fx.index(false);
    assert_eq!(stats.get("already_present"), 2);
    assert_eq!(stats.get("inserted") + stats.get("updated"), 0);
    let unchanged: Option<Value> = sqlx::query_scalar("SELECT chapters FROM episodes WHERE s3_key = $1")
        .bind(&with_chapters)
        .fetch_one(&pool)
        .await
        .unwrap();
    assert!(unchanged.is_some());

    // --overwrite rewrites show, date, slot and chapters; a missing chapters
    // list clears them.
    let stats = fx.index(true);
    assert_eq!(stats.get("updated"), 2);
    assert_eq!(stats.get("chapters_filled"), 1);
    assert_eq!(stats.get("chapters_cleared"), 1);
    let (name, aired_on, time_slot, chapters_after): (String, chrono::NaiveDate, Option<String>, Option<Value>) =
        sqlx::query_as(
            "SELECT s.name, e.aired_on, e.time_slot, e.chapters
             FROM episodes e JOIN shows s ON s.id = e.show_id WHERE e.s3_key = $1",
        )
        .bind(&with_chapters)
        .fetch_one(&pool)
        .await
        .unwrap();
    assert_eq!(
        (name.as_str(), aired_on, time_slot.as_deref(), chapters_after),
        ("Renamed", date("2026-03-21"), Some("0800_0900"), None)
    );
    let filled: Value = sqlx::query_scalar("SELECT chapters FROM episodes WHERE s3_key = $1")
        .bind(&without_chapters)
        .fetch_one(&pool)
        .await
        .unwrap();
    assert_eq!(filled, json!([{ "title": "new", "start": 0, "end": 1000 }]));

    // A vanished audio file soft-deletes its episode; its return restores it
    // with the same id.
    let id_before = episode_id(&pool, &without_chapters).await;
    fx.delete(&without_chapters).await;
    assert_eq!(fx.index(false).get("soft_deleted"), 1);
    let deleted: bool = sqlx::query_scalar("SELECT deleted FROM episodes WHERE id = $1")
        .bind(id_before)
        .fetch_one(&pool)
        .await
        .unwrap();
    assert!(deleted);
    fx.put(&without_chapters, audio.clone()).await;
    let stats = fx.index(false);
    assert_eq!((stats.get("restored"), stats.get("soft_deleted")), (1, 0));
    assert_eq!(episode_id(&pool, &without_chapters).await, id_before);

    fx.cleanup().await;
}

#[tokio::test]
#[ignore = "needs Silo and Postgres: run scripts/e2e.sh"]
async fn indexer_on_an_empty_bucket_and_a_missing_one() {
    let fx = Fixture::new().await;
    fx.index(false).assert(&[]);

    let output = fx
        .command(&["index"])
        .env("S3_BUCKET", "s3player-e2e-no-such-bucket")
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(stderr(&output).contains("NoSuchBucket"), "{}", stderr(&output));
    fx.cleanup().await;
}

#[tokio::test]
#[ignore = "needs Silo and Postgres: run scripts/e2e.sh"]
async fn database_settings_from_discrete_postgres_variables() {
    let fx = Fixture::new().await;
    let url: reqwest::Url = fx.database_url.parse().unwrap();
    let output = fx
        .command(&["index"])
        .env_remove("DATABASE_URL")
        .env("POSTGRES_HOST", url.host_str().unwrap())
        .env("POSTGRES_PORT", url.port().unwrap_or(5432).to_string())
        .env("POSTGRES_USER", url.username())
        .env("POSTGRES_PASSWORD", url.password().unwrap_or_default())
        .env("POSTGRES_DATABASE", &fx.database)
        .output()
        .unwrap();
    assert!(output.status.success(), "{}", stderr(&output));

    let output = fx.command(&["index"]).env("DATABASE_URL", "not a url").output().unwrap();
    assert!(!output.status.success());
    assert!(stderr(&output).contains("invalid DATABASE_URL"), "{}", stderr(&output));
    fx.cleanup().await;
}

#[tokio::test]
#[ignore = "needs Silo and Postgres: run scripts/e2e.sh"]
async fn auth_gate_login_flows() {
    let fx = Fixture::new().await;
    let server = fx.server().ready().await;
    let http = &server.http;

    // No credentials: API is 401 JSON, pages redirect to /login.
    let response = http.get(server.url("/api/shows/stations")).send().await.unwrap();
    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    assert_eq!(response.json::<Value>().await.unwrap(), json!({ "detail": "unauthenticated" }));
    let response = http.get(server.url("/stations?x=1")).send().await.unwrap();
    assert_eq!(response.status(), StatusCode::SEE_OTHER);
    assert_eq!(response.headers()[header::LOCATION], "/login?next=%2Fstations%3Fx%3D1");

    // The HTML form carries a sanitized `next`.
    let page = http.get(server.url("/login?next=//evil")).send().await.unwrap();
    assert_eq!(page.status(), StatusCode::OK);
    let html = page.text().await.unwrap();
    assert!(html.contains(r#"name="next" value="/""#), "{html}");

    let response = http
        .post(server.url("/login"))
        .form(&[("password", "wrong"), ("next", "/stations")])
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    assert!(response.text().await.unwrap().contains("Wrong password."));

    let response = http
        .post(server.url("/login"))
        .form(&[("password", PASSWORD), ("next", "/stations")])
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::SEE_OTHER);
    assert_eq!(response.headers()[header::LOCATION], "/stations");
    let cookie = response.headers()[header::SET_COOKIE].to_str().unwrap();
    let cookie = cookie.split(';').next().unwrap().to_string();

    let mut headers = HeaderMap::new();
    headers.insert(header::COOKIE, cookie.parse().unwrap());
    let (status, body) = send_json(http.get(server.url("/api/shows/stations")).headers(headers)).await;
    assert_eq!((status, body), (StatusCode::OK, json!({ "stations": [] })));

    let (status, body) = send_json(http.post(server.url("/api/auth/login")).json(&json!({ "password": "nope" }))).await;
    assert_eq!((status, body), (StatusCode::UNAUTHORIZED, json!({ "detail": "wrong_password" })));
    let (status, _) = send_json(http.post(server.url("/api/auth/login")).json(&json!({}))).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);

    let (status, body) = server.get_json("/api/does-not-exist").await;
    assert_eq!((status, body), (StatusCode::NOT_FOUND, json!({ "detail": "not found" })));

    drop(server);
    fx.cleanup().await;
}

#[tokio::test]
#[ignore = "needs Silo and Postgres: run scripts/e2e.sh"]
async fn catalog_browsing_and_favorites() {
    let mut fx = Fixture::new().await;
    seed_catalog(&fx).await;
    fx.index(false);
    let pool = fx.pool().await;
    let morning = show_id(&pool, STATION, "Morning").await;
    let evening = show_id(&pool, STATION, "Evening").await;
    let morning_a = episode_id(&pool, &key(STATION, "2026-03-22", "morning_a.m4a")).await;
    let morning_b = episode_id(&pool, &key(STATION, "2026-04-05", "morning_b.m4a")).await;
    let server = fx.server().ready().await;

    let (status, body) = server.get_json("/api/shows/stations").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body,
        json!({ "stations": [
            { "id": "rthk-radio1", "show_count": 2 },
            { "id": "rthk-radio2", "show_count": 1 },
        ] })
    );

    let (_, body) = server.get_json(&format!("/api/shows/stations/{STATION}/shows")).await;
    assert_eq!(
        body,
        json!({ "shows": [
            { "id": evening, "name": "Evening", "episode_count": 1, "is_favorite": false },
            { "id": morning, "name": "Morning", "episode_count": 2, "is_favorite": false },
        ] })
    );
    let (_, body) = server.get_json("/api/shows/stations/nowhere/shows").await;
    assert_eq!(body, json!({ "shows": [] }));

    let morning_detail = json!({ "id": morning, "station": STATION, "name": "Morning", "episode_count": 2 });
    let (_, body) = server.get_json(&format!("/api/shows/{morning}")).await;
    assert_eq!(body, morning_detail);

    let (_, body) = server.get_json(&format!("/api/shows/{morning}/months")).await;
    assert_eq!(
        body,
        json!({ "show": morning_detail, "months": [
            { "year": 2026, "month": 4, "episode_count": 1 },
            { "year": 2026, "month": 3, "episode_count": 1 },
        ] })
    );

    let (_, body) = server.get_json(&format!("/api/shows/{morning}/months/2026/3/episodes")).await;
    assert_eq!(
        body,
        json!({ "show": morning_detail, "episodes": [{
            "id": morning_a,
            "aired_on": "2026-03-22",
            "time_slot": "0600_0700",
            "s3_key": key(STATION, "2026-03-22", "morning_a.m4a"),
            "chapters": [
                { "title": "one", "start": 0, "end": 1000 },
                { "title": "two", "start": 1000, "end": 2000 },
            ],
        }] })
    );
    let (_, body) = server.get_json(&format!("/api/shows/{morning}/months/2025/12/episodes")).await;
    assert_eq!(body["episodes"], json!([]));

    let (_, body) = server.get_json(&format!("/api/shows/{morning}/recent-episodes?limit=1")).await;
    assert_eq!(
        body,
        json!({ "show": morning_detail, "episodes": [{
            "id": morning_b, "aired_on": "2026-04-05", "time_slot": "0600_0700",
            "show_id": morning, "show_name": "Morning", "station": STATION,
            "position_ms": 0, "duration_ms": null, "completed": false, "last_played_at": null,
        }] })
    );
    let (_, body) = server.get_json(&format!("/api/shows/{morning}/recent-episodes")).await;
    assert_eq!(body["episodes"].as_array().unwrap().len(), 2);

    let (_, body) = server.get_json(&format!("/api/shows/episodes/{morning_b}")).await;
    assert_eq!(
        body,
        json!({
            "id": morning_b, "aired_on": "2026-04-05", "time_slot": "0600_0700",
            "s3_key": key(STATION, "2026-04-05", "morning_b.m4a"), "chapters": null,
            "show": morning_detail,
        })
    );

    for path in [
        "/api/shows/999999".to_string(),
        "/api/shows/999999/months".to_string(),
        "/api/shows/999999/recent-episodes".to_string(),
        "/api/shows/999999/months/2026/3/episodes".to_string(),
        "/api/shows/episodes/999999".to_string(),
    ] {
        let (status, _) = server.get_json(&path).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{path}");
    }
    for path in ["/api/shows/0", "/api/shows/1/months/2026/13/episodes", "/api/shows/1/recent-episodes?limit=0"] {
        let (status, _) = server.get_json(path).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{path}");
    }

    // Favorites: idempotent add/remove, flagged in the station listing,
    // ordered by latest aired episode.
    for show in [morning, evening, morning] {
        let (status, body) = send_json(server.post(&format!("/api/shows/{show}/favorite"))).await;
        assert_eq!((status, body), (StatusCode::OK, json!({ "status": "ok" })));
    }
    let (status, _) = send_json(server.post("/api/shows/999999/favorite")).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (_, body) = server.get_json("/api/shows/favorites").await;
    let favorites = body["favorites"].as_array().unwrap();
    let summary: Vec<(i64, i64, &str)> = favorites
        .iter()
        .map(|f| {
            (
                f["id"].as_i64().unwrap(),
                f["episode_count"].as_i64().unwrap(),
                f["latest_aired_on"].as_str().unwrap(),
            )
        })
        .collect();
    assert_eq!(
        summary,
        vec![(evening as i64, 1, "2026-04-06"), (morning as i64, 2, "2026-04-05")]
    );
    let (_, body) = server.get_json(&format!("/api/shows/stations/{STATION}/shows")).await;
    assert!(body["shows"].as_array().unwrap().iter().all(|s| s["is_favorite"] == json!(true)));

    for _ in 0..2 {
        let (status, _) = send_json(server.delete(&format!("/api/shows/{evening}/favorite"))).await;
        assert_eq!(status, StatusCode::OK);
    }
    let (_, body) = server.get_json("/api/shows/favorites").await;
    assert_eq!(body["favorites"].as_array().unwrap().len(), 1);

    // Soft-deleted episodes drop out of counts and detail.
    fx.delete(&key(STATION, "2026-03-22", "morning_a.m4a")).await;
    fx.index(false);
    let (status, _) = server.get_json(&format!("/api/shows/episodes/{morning_a}")).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (_, body) = server.get_json(&format!("/api/shows/{morning}")).await;
    assert_eq!(body["episode_count"], json!(1));
    let (_, body) = server.get_json(&format!("/api/shows/{morning}/months")).await;
    assert_eq!(body["months"], json!([{ "year": 2026, "month": 4, "episode_count": 1 }]));

    drop(server);
    fx.cleanup().await;
}

#[tokio::test]
#[ignore = "needs Silo and Postgres: run scripts/e2e.sh"]
async fn audio_proxy_ranges_and_presigned_url() {
    let mut fx = Fixture::new().await;
    seed_catalog(&fx).await;
    fx.index(false);
    let pool = fx.pool().await;
    let m4a_key = key(STATION, "2026-03-22", "morning_a.m4a");
    let m4a = episode_id(&pool, &m4a_key).await;
    let ogg = episode_id(&pool, &key(STATION, "2026-04-06", "evening.ogg")).await;
    let server = fx.server().ready().await;
    let audio = audio_bytes(1000);

    let response = server.get(&format!("/api/shows/episodes/{m4a}/audio")).send().await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(response.headers()[header::CONTENT_TYPE], "audio/mp4");
    assert_eq!(response.headers()[header::ACCEPT_RANGES], "bytes");
    assert_eq!(response.headers()[header::CONTENT_LENGTH], "1000");
    assert_eq!(response.bytes().await.unwrap().as_ref(), audio.as_slice());

    let response = server
        .get(&format!("/api/shows/episodes/{ogg}/audio"))
        .header(header::RANGE, "bytes=100-199")
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::PARTIAL_CONTENT);
    assert_eq!(response.headers()[header::CONTENT_TYPE], "audio/ogg");
    assert_eq!(response.headers()[header::CONTENT_RANGE], "bytes 100-199/1000");
    assert_eq!(response.headers()[header::CONTENT_LENGTH], "100");
    assert_eq!(response.bytes().await.unwrap().as_ref(), &audio[100..200]);

    let response = server
        .get(&format!("/api/shows/episodes/{m4a}/audio"))
        .header(header::RANGE, "bytes=900-")
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::PARTIAL_CONTENT);
    assert_eq!(response.headers()[header::CONTENT_RANGE], "bytes 900-999/1000");

    let (status, body) =
        send_json(server.get(&format!("/api/shows/episodes/{m4a}/audio")).header(header::RANGE, "bytes=5000-")).await;
    assert_eq!((status, body), (StatusCode::RANGE_NOT_SATISFIABLE, json!({ "detail": "range not satisfiable" })));

    // The presigned URL works without the app's credentials.
    let (status, body) = server.get_json(&format!("/api/shows/episodes/{m4a}/audio_url")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["expires_in"], json!(3600));
    let url = body["url"].as_str().unwrap();
    assert!(url.contains(&format!("/{}/", fx.bucket)), "path-style URL: {url}");
    let direct = reqwest::get(url).await.unwrap();
    assert_eq!(direct.status(), StatusCode::OK);
    assert_eq!(direct.bytes().await.unwrap().as_ref(), audio.as_slice());

    // Indexed but gone from S3: 404, not a server error.
    fx.delete(&m4a_key).await;
    let (status, body) = send_json(server.get(&format!("/api/shows/episodes/{m4a}/audio"))).await;
    assert_eq!((status, body), (StatusCode::NOT_FOUND, json!({ "detail": "audio not found" })));

    for path in ["/api/shows/episodes/999999/audio", "/api/shows/episodes/999999/audio_url"] {
        let (status, body) = server.get_json(path).await;
        assert_eq!((status, body), (StatusCode::NOT_FOUND, json!({ "detail": "episode not found" })), "{path}");
    }

    drop(server);
    fx.cleanup().await;
}

#[tokio::test]
#[ignore = "needs Silo and Postgres: run scripts/e2e.sh"]
async fn chapter_summaries_from_s3() {
    let mut fx = Fixture::new().await;
    seed_catalog(&fx).await;
    fx.index(false);
    let pool = fx.pool().await;
    let with = episode_id(&pool, &key(STATION, "2026-03-22", "morning_a.m4a")).await;
    let without = episode_id(&pool, &key(STATION, "2026-04-05", "morning_b.m4a")).await;
    let prefix = format!("summaries/{STATION}/2026/03/22/morning_a_summary/");
    fx.put(&format!("{prefix}chapter_10.md"), "# ten").await;
    fx.put(&format!("{prefix}chapter_02.md"), "# 二").await;
    fx.put(&format!("{prefix}chapter_01.md"), "# one").await;
    fx.put(&format!("{prefix}index.md"), "ignored").await;
    fx.put(&format!("{prefix}chapter_03.md"), vec![0xff, 0xfe]).await;
    let server = fx.server().ready().await;

    let (status, body) = server.get_json(&format!("/api/shows/episodes/{with}/chapter_summaries")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body,
        json!({ "summaries": [
            { "index": 1, "content": "# one" },
            { "index": 2, "content": "# 二" },
            { "index": 10, "content": "# ten" },
        ] })
    );
    let (_, body) = server.get_json(&format!("/api/shows/episodes/{without}/chapter_summaries")).await;
    assert_eq!(body, json!({ "summaries": [] }));
    let (status, _) = server.get_json("/api/shows/episodes/999999/chapter_summaries").await;
    assert_eq!(status, StatusCode::NOT_FOUND);

    drop(server);
    fx.cleanup().await;
}

#[tokio::test]
#[ignore = "needs Silo and Postgres: run scripts/e2e.sh"]
async fn player_session_progress_and_home_rows() {
    let mut fx = Fixture::new().await;
    seed_catalog(&fx).await;
    fx.index(false);
    let pool = fx.pool().await;
    let a = episode_id(&pool, &key(STATION, "2026-03-22", "morning_a.m4a")).await;
    let b = episode_id(&pool, &key(STATION, "2026-04-05", "morning_b.m4a")).await;
    let c = episode_id(&pool, &key(STATION, "2026-04-06", "evening.ogg")).await;
    let server = fx.server().ready().await;

    let claim = || async {
        let (status, body) = send_json(server.post("/api/player/session/claim")).await;
        assert_eq!(status, StatusCode::OK);
        let token = body["session_token"].as_str().unwrap().to_string();
        assert_eq!(token.len(), 48);
        token
    };
    let save = |token: String, id: i32, body: Value| {
        send_json(
            server
                .post(&format!("/api/player/episodes/{id}/progress"))
                .header("X-Player-Session", token)
                .json(&body),
        )
    };
    let progress = |id: i32| server.get_json(&format!("/api/player/episodes/{id}/progress"));
    let ids = |body: &Value| -> Vec<i64> {
        body["episodes"].as_array().unwrap().iter().map(|e| e["id"].as_i64().unwrap()).collect()
    };

    // Nothing recorded yet.
    let (_, body) = progress(a).await;
    assert_eq!(
        body,
        json!({ "position_ms": 0, "duration_ms": null, "completed": false, "last_played_at": null })
    );

    let first = claim().await;
    let (status, _) = send_json(server.post("/api/player/session/validate").header("X-Player-Session", &first)).await;
    assert_eq!(status, StatusCode::OK);

    assert_eq!(
        save(first.clone(), a, json!({ "position_ms": 5000, "duration_ms": 600000 })).await,
        (StatusCode::OK, json!({ "status": "ok" }))
    );
    // A later save without duration keeps the known one.
    save(first.clone(), a, json!({ "position_ms": 6000 })).await;
    let (_, body) = progress(a).await;
    assert_eq!((body["position_ms"].clone(), body["duration_ms"].clone()), (json!(6000), json!(600000)));
    assert!(body["last_played_at"].is_string());

    // Within 30s of the end is not "in progress"; completed moves to history.
    save(first.clone(), b, json!({ "position_ms": 590000, "duration_ms": 600000 })).await;
    save(first.clone(), c, json!({ "position_ms": 600000, "duration_ms": 600000, "completed": true })).await;
    let (_, body) = server.get_json("/api/player/in-progress").await;
    assert_eq!(ids(&body), vec![a as i64]);
    assert_eq!(body["episodes"][0]["show_name"], json!("Morning"));
    let (_, body) = server.get_json("/api/player/recent-completed").await;
    assert_eq!(ids(&body), vec![c as i64]);
    let (status, _) = server.get_json("/api/player/in-progress?limit=51").await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);

    // The show's recent episodes carry the play state.
    let morning = show_id(&pool, STATION, "Morning").await;
    let (_, body) = server.get_json(&format!("/api/shows/{morning}/recent-episodes")).await;
    let played = body["episodes"].as_array().unwrap().iter().find(|e| e["id"] == json!(a)).unwrap();
    assert_eq!(played["position_ms"], json!(6000));

    // Validation and missing episodes.
    let (status, _) = save(first.clone(), a, json!({ "position_ms": -1 })).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    let (status, _) = save(first.clone(), a, json!({ "duration_ms": 1 })).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    let (status, body) = save(first.clone(), 999999, json!({ "position_ms": 1 })).await;
    assert_eq!((status, body), (StatusCode::NOT_FOUND, json!({ "detail": "episode not found" })));

    // A second claim displaces the first everywhere.
    let second = claim().await;
    assert_ne!(first, second);
    let displaced = (StatusCode::CONFLICT, json!({ "detail": "session displaced" }));
    assert_eq!(save(first.clone(), a, json!({ "position_ms": 1 })).await, displaced);
    assert_eq!(
        send_json(server.post("/api/player/session/validate").header("X-Player-Session", &first)).await,
        displaced
    );
    assert_eq!(
        send_json(server.delete(&format!("/api/player/episodes/{a}/progress")).header("X-Player-Session", &first)).await,
        displaced
    );
    let (_, body) = progress(a).await;
    assert_eq!(body["position_ms"], json!(6000));

    // Delete is idempotent and drops the episode from the home rows.
    for _ in 0..2 {
        let (status, _) = send_json(
            server.delete(&format!("/api/player/episodes/{a}/progress")).header("X-Player-Session", &second),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
    }
    let (_, body) = server.get_json("/api/player/in-progress").await;
    assert_eq!(ids(&body), Vec::<i64>::new());

    // Soft-deleted episodes leave the home rows too.
    fx.delete(&key(STATION, "2026-04-06", "evening.ogg")).await;
    fx.index(false);
    let (_, body) = server.get_json("/api/player/recent-completed").await;
    assert_eq!(ids(&body), Vec::<i64>::new());

    drop(server);
    fx.cleanup().await;
}

#[tokio::test]
#[ignore = "needs Silo and Postgres: run scripts/e2e.sh"]
async fn server_exits_cleanly_on_sigterm() {
    let fx = Fixture::new().await;
    let mut server = fx.server().ready().await;
    let status = server.terminate().expect("server did not exit on SIGTERM");
    assert!(status.success(), "{status}");
    drop(server);

    // And refuses to start on an unreachable database.
    let output = fx
        .command(&["server"])
        .env("SITE_PASSWORD", PASSWORD)
        .env("DATABASE_URL", format!("postgres://nobody@127.0.0.1:{}/none", free_port()))
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(stderr(&output).contains("failed to connect to Postgres"), "{}", stderr(&output));
    fx.cleanup().await;
}

#[test]
fn e2e_suite_is_wired_to_the_runner_script() {
    // Guards against the script and the suite drifting apart.
    let script = std::fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/e2e.sh")).unwrap();
    for var in [
        "S3PLAYER_E2E_S3_ENDPOINT",
        "S3PLAYER_E2E_S3_ACCESS_KEY_ID",
        "S3PLAYER_E2E_S3_SECRET_ACCESS_KEY",
        "S3PLAYER_E2E_S3_REGION",
        "S3PLAYER_E2E_DATABASE_URL",
    ] {
        assert!(script.contains(var), "scripts/e2e.sh does not set {var}");
    }
}
