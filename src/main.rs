mod assets;
mod audio;
mod auth;
mod cli;
mod db;
mod error;
mod indexer;
mod player;
mod s3;
mod server;
mod show_metadata;
mod shows;
mod summaries;
#[cfg(test)]
mod test_support;

use clap::Parser;
use cli::{Cli, Commands};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // A missing .env is fine; settings then come from the real environment.
    let _ = dotenvy::dotenv();
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info,sqlx::postgres::notice=warn")).init();

    match Cli::parse().command {
        Commands::Server(args) => {
            let pool = db::connect(&args.db).await?;
            let s3 = args.s3.build().await;
            let state = server::AppState::new(pool, s3, &args.site_password);
            server::serve(state, &args.host, args.port).await
        }
        Commands::Index(args) => {
            let pool = db::connect(&args.db).await?;
            let s3 = args.s3.build().await;
            let result = indexer::run(&pool, &s3, args.overwrite).await;
            pool.close().await;
            result
        }
    }
}
