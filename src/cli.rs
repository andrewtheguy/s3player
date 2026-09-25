use clap::{Args, Parser, Subcommand};

/// Every setting also reads from its environment variable; a `.env` in the
/// working directory is loaded first.
#[derive(Parser)]
#[command(name = "s3player", version, about = "Password-gated player for S3-hosted radio recordings")]
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
}

#[derive(Subcommand)]
pub enum Commands {
    /// Run the web server
    Server(ServerArgs),
    /// Index audio files from S3 into Postgres (one-shot)
    Index(IndexArgs),
}

#[derive(Args)]
pub struct ServerArgs {
    /// Bind address
    #[arg(long, env = "SERVER_HOST", default_value = "127.0.0.1")]
    pub host: String,

    /// Bind port
    #[arg(long, env = "SERVER_PORT", default_value_t = 8000)]
    pub port: u16,

    /// Single password protecting the app
    #[arg(long, env = "SITE_PASSWORD", hide_env_values = true)]
    pub site_password: String,

    #[command(flatten)]
    pub s3: S3Args,

    #[command(flatten)]
    pub db: DbArgs,
}

#[derive(Args)]
pub struct IndexArgs {
    /// Overwrite existing episode rows (show_id, aired_on, time_slot, chapters)
    /// from S3 metadata. Default leaves already-indexed episodes untouched.
    #[arg(long)]
    pub overwrite: bool,

    #[command(flatten)]
    pub s3: S3Args,

    #[command(flatten)]
    pub db: DbArgs,
}

#[derive(Args)]
pub struct S3Args {
    /// S3-compatible endpoint URL
    #[arg(long, env = "S3_ENDPOINT")]
    pub s3_endpoint: String,

    /// Bucket containing the recordings
    #[arg(long, env = "S3_BUCKET")]
    pub s3_bucket: String,

    /// Region for the S3 client
    #[arg(long, env = "S3_REGION")]
    pub s3_region: String,

    #[arg(long, env = "S3_ACCESS_KEY_ID", hide_env_values = true)]
    pub s3_access_key_id: String,

    #[arg(long, env = "S3_SECRET_ACCESS_KEY", hide_env_values = true)]
    pub s3_secret_access_key: String,
}

/// Either `DATABASE_URL`, or all five `POSTGRES_*` pieces (handy when they are
/// injected separately from a Kubernetes ConfigMap/Secret).
#[derive(Args)]
pub struct DbArgs {
    /// Postgres URL (postgres://…)
    #[arg(long, env = "DATABASE_URL", hide_env_values = true, required_unless_present_all = ["postgres_host", "postgres_port", "postgres_user", "postgres_password", "postgres_database"])]
    pub database_url: Option<String>,

    #[arg(long, env = "POSTGRES_HOST")]
    pub postgres_host: Option<String>,

    #[arg(long, env = "POSTGRES_PORT")]
    pub postgres_port: Option<u16>,

    #[arg(long, env = "POSTGRES_USER")]
    pub postgres_user: Option<String>,

    #[arg(long, env = "POSTGRES_PASSWORD", hide_env_values = true)]
    pub postgres_password: Option<String>,

    #[arg(long, env = "POSTGRES_DATABASE")]
    pub postgres_database: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::CommandFactory;

    #[test]
    fn cli_definition_is_valid() {
        Cli::command().debug_assert();
    }

    const S3_FLAGS: &[&str] = &[
        "--s3-endpoint=http://s3",
        "--s3-bucket=b",
        "--s3-region=r",
        "--s3-access-key-id=k",
        "--s3-secret-access-key=s",
    ];

    fn parse(args: &[&str]) -> Result<Cli, clap::Error> {
        Cli::try_parse_from(["s3player"].iter().chain(args).chain(S3_FLAGS))
    }

    #[test]
    fn server_flags() {
        let cli = parse(&[
            "server",
            "--host=0.0.0.0",
            "--port=9001",
            "--site-password=pw",
            "--database-url=postgres://x",
        ])
        .unwrap();
        let Commands::Server(args) = cli.command else {
            panic!("expected server");
        };
        assert_eq!((args.host.as_str(), args.port, args.site_password.as_str()), ("0.0.0.0", 9001, "pw"));
        assert_eq!(args.s3.s3_endpoint, "http://s3");
        assert_eq!(args.s3.s3_bucket, "b");
        assert_eq!(args.db.database_url.as_deref(), Some("postgres://x"));
        assert!(parse(&["server", "--port=nope", "--site-password=pw", "--database-url=x"]).is_err());
    }

    #[test]
    fn index_flags_and_postgres_pieces() {
        let pieces = [
            "--postgres-host=h",
            "--postgres-port=5432",
            "--postgres-user=u",
            "--postgres-password=p",
            "--postgres-database=d",
        ];
        let args: Vec<&str> = ["index", "--overwrite"].into_iter().chain(pieces).collect();
        let Commands::Index(args) = parse(&args).unwrap().command else {
            panic!("expected index");
        };
        assert!(args.overwrite);
        assert_eq!(args.db.database_url, None);
        assert_eq!(args.db.postgres_port, Some(5432));
        assert_eq!(args.db.postgres_database.as_deref(), Some("d"));
    }
}
