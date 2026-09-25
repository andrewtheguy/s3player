//! Single shared-password gate. The auth token is a deterministic
//! HMAC-SHA256 of a fixed message keyed by the site password: browsers get it
//! as the `s3player_auth` cookie from the HTML form at `/login`; other clients
//! get it from `POST /api/auth/login` and send it as a bearer token.

use axum::Json;
use axum::extract::{Query, Request, State};
use axum::http::{HeaderMap, StatusCode, header};
use axum::middleware::Next;
use axum::response::{Html, IntoResponse, Redirect, Response};
use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use subtle::ConstantTimeEq;

use crate::error::AppError;
use crate::server::{ApiForm, ApiJson, AppState};

pub const COOKIE_NAME: &str = "s3player_auth";

/// Paths under `/api/` that need no auth.
const API_AUTH_EXEMPT: &[&str] = &["/api/auth/login"];

pub fn expected_token(password: &str) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(password.as_bytes())
        .expect("HMAC accepts keys of any length");
    mac.update(b"authenticated");
    hex::encode(mac.finalize().into_bytes())
}

fn ct_eq(a: &str, b: &str) -> bool {
    a.as_bytes().ct_eq(b.as_bytes()).into()
}

fn cookie_value<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers
        .get_all(header::COOKIE)
        .iter()
        .filter_map(|v| v.to_str().ok())
        .flat_map(|v| v.split(';'))
        .filter_map(|pair| pair.trim().split_once('='))
        .find(|(k, _)| *k == name)
        .map(|(_, v)| v)
}

pub fn is_authenticated(headers: &HeaderMap, token: &str) -> bool {
    if cookie_value(headers, COOKIE_NAME).is_some_and(|c| !c.is_empty() && ct_eq(c, token)) {
        return true;
    }
    let Some(auth) = headers.get(header::AUTHORIZATION).and_then(|v| v.to_str().ok()) else {
        return false;
    };
    let (scheme, bearer) = auth.split_once(' ').unwrap_or((auth, ""));
    scheme.eq_ignore_ascii_case("bearer") && !bearer.is_empty() && ct_eq(bearer, token)
}

/// Only same-origin absolute paths are allowed as post-login redirect targets.
pub fn safe_next(next: &str) -> &str {
    if next.starts_with('/') && !next.starts_with("//") {
        next
    } else {
        "/"
    }
}

/// `/login` is open; `/api/*` answers 401 JSON without auth; everything else
/// (the SPA) redirects to `/login?next=…`.
pub async fn site_password_gate(State(state): State<AppState>, req: Request, next: Next) -> Response {
    let path = req.uri().path();
    if path == "/login" || API_AUTH_EXEMPT.contains(&path) {
        return next.run(req).await;
    }
    if is_authenticated(req.headers(), &state.auth_token) {
        return next.run(req).await;
    }
    if path.starts_with("/api/") {
        return AppError::Unauthorized("unauthenticated").into_response();
    }
    let target = match req.uri().query() {
        Some(q) if !q.is_empty() => format!("{path}?{q}"),
        _ => path.to_string(),
    };
    Redirect::to(&format!("/login?next={}", urlencoding::encode(&target))).into_response()
}

#[derive(Deserialize)]
pub struct TokenLoginRequest {
    password: String,
}

#[derive(Serialize)]
pub struct TokenLoginResponse {
    token: String,
}

/// `POST /api/auth/login` — exchange the site password for the bearer token.
pub async fn api_login(
    State(state): State<AppState>,
    ApiJson(body): ApiJson<TokenLoginRequest>,
) -> Result<Json<TokenLoginResponse>, AppError> {
    if !ct_eq(&body.password, &state.site_password) {
        return Err(AppError::Unauthorized("wrong_password"));
    }
    Ok(Json(TokenLoginResponse {
        token: state.auth_token.to_string(),
    }))
}

const LOGIN_HTML: &str = r#"<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>s3player — Sign in</title>
  <style>
    :root { color-scheme: dark; }
    body {
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      display: grid; place-items: center; min-height: 100vh;
      margin: 0; background: #0f1115; color: #e6e6e6;
    }
    form {
      display: flex; flex-direction: column; gap: 0.75rem;
      min-width: 19rem; padding: 2rem; background: #181b22;
      border-radius: 0.75rem; box-shadow: 0 1px 0 #2a2f3a, 0 8px 30px #0008;
    }
    h1 { margin: 0 0 0.25rem; font-size: 1.05rem; letter-spacing: 0.02em; }
    label { font-size: 0.8rem; color: #a1a7b3; }
    input[type=password] {
      padding: 0.55rem 0.75rem; border-radius: 0.4rem;
      border: 1px solid #2a2f3a; background: #0c0f14; color: #e6e6e6;
      font-size: 0.95rem;
    }
    input[type=password]:focus { outline: 2px solid #4f8cff; outline-offset: 1px; }
    button {
      padding: 0.55rem 0.75rem; border: 0; border-radius: 0.4rem;
      background: #4f8cff; color: white; font-weight: 600; cursor: pointer;
    }
    button:hover { background: #6da0ff; }
    .error { color: #ff7b7b; font-size: 0.85rem; margin: 0; }
  </style>
</head>
<body>
  <form method="post" action="/login">
    <h1>s3player — sign in</h1>
    {error_html}
    <input type="hidden" name="next" value="{next_value}">
    <label for="password">Password</label>
    <input id="password" type="password" name="password" autofocus required>
    <button type="submit">Continue</button>
  </form>
</body>
</html>
"#;

fn escape_html(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#x27;"),
            _ => out.push(c),
        }
    }
    out
}

fn render_login(next: &str, error: Option<&str>) -> Html<String> {
    let error_html = error
        .map(|e| format!(r#"<p class="error">{}</p>"#, escape_html(e)))
        .unwrap_or_default();
    Html(
        LOGIN_HTML
            .replace("{error_html}", &error_html)
            .replace("{next_value}", &escape_html(next)),
    )
}

#[derive(Deserialize)]
pub struct LoginQuery {
    next: Option<String>,
}

/// `GET /login` — the HTML sign-in form.
pub async fn login_page(Query(query): Query<LoginQuery>) -> Html<String> {
    render_login(safe_next(query.next.as_deref().unwrap_or("/")), None)
}

#[derive(Deserialize)]
pub struct LoginForm {
    password: String,
    next: Option<String>,
}

/// `POST /login` — check the password and set the browser-session auth cookie.
pub async fn login_submit(State(state): State<AppState>, ApiForm(form): ApiForm<LoginForm>) -> Response {
    let target = safe_next(form.next.as_deref().unwrap_or("/"));
    if !ct_eq(&form.password, &state.site_password) {
        return (StatusCode::UNAUTHORIZED, render_login(target, Some("Wrong password."))).into_response();
    }
    // No Max-Age/Expires: a browser-session cookie.
    let cookie = format!("{COOKIE_NAME}={}; HttpOnly; Path=/; SameSite=Lax", state.auth_token);
    ([(header::SET_COOKIE, cookie)], Redirect::to(target)).into_response()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::{body_json, test_state};
    use axum::body::Body;
    use axum::http::Request;
    use tower::ServiceExt;

    #[test]
    fn safe_next_rejects_offsite_targets() {
        assert_eq!(safe_next("/stations?x=1"), "/stations?x=1");
        assert_eq!(safe_next("//evil.example"), "/");
        assert_eq!(safe_next("https://evil.example"), "/");
        assert_eq!(safe_next(""), "/");
    }

    #[test]
    fn escape_html_escapes_attribute_breakers() {
        assert_eq!(escape_html(r#""><script>&'"#), "&quot;&gt;&lt;script&gt;&amp;&#x27;");
    }

    #[tokio::test]
    async fn login_sets_browser_session_cookie() {
        let app = crate::server::router(test_state());
        let response = app
            .oneshot(
                Request::post("/login")
                    .header(header::CONTENT_TYPE, "application/x-www-form-urlencoded")
                    .body(Body::from("password=test-password&next=%2Fstations"))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::SEE_OTHER);
        assert_eq!(response.headers()[header::LOCATION], "/stations");
        let set_cookie = response.headers()[header::SET_COOKIE].to_str().unwrap();
        assert!(set_cookie.starts_with(&format!("{COOKIE_NAME}={}", expected_token("test-password"))));
        assert!(set_cookie.contains("HttpOnly"));
        assert!(!set_cookie.contains("Max-Age"));
        assert!(!set_cookie.to_lowercase().contains("expires="));
    }

    #[tokio::test]
    async fn login_wrong_password_rerenders_form() {
        let app = crate::server::router(test_state());
        let response = app
            .oneshot(
                Request::post("/login")
                    .header(header::CONTENT_TYPE, "application/x-www-form-urlencoded")
                    .body(Body::from("password=nope&next=%2F%2Fevil"))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
        assert!(response.headers().get(header::SET_COOKIE).is_none());
    }

    #[tokio::test]
    async fn api_login_returns_token_for_correct_password() {
        let app = crate::server::router(test_state());
        let response = app
            .oneshot(
                Request::post("/api/auth/login")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(r#"{"password":"test-password"}"#))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert!(response.headers().get(header::SET_COOKIE).is_none());
        assert_eq!(
            body_json(response).await,
            serde_json::json!({ "token": expected_token("test-password") })
        );
    }

    #[tokio::test]
    async fn api_login_rejects_wrong_password() {
        let app = crate::server::router(test_state());
        let response = app
            .oneshot(
                Request::post("/api/auth/login")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(r#"{"password":"nope"}"#))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
        assert_eq!(body_json(response).await, serde_json::json!({ "detail": "wrong_password" }));
    }

    #[tokio::test]
    async fn missing_or_bad_auth_returns_401_json_for_api() {
        for auth in [None, Some("Bearer not-the-real-token")] {
            let app = crate::server::router(test_state());
            let mut req = Request::get("/api/shows/stations");
            if let Some(auth) = auth {
                req = req.header(header::AUTHORIZATION, auth);
            }
            let response = app.oneshot(req.body(Body::empty()).unwrap()).await.unwrap();
            assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
            assert_eq!(body_json(response).await, serde_json::json!({ "detail": "unauthenticated" }));
        }
    }

    #[tokio::test]
    async fn unauthenticated_spa_route_redirects_to_login() {
        let app = crate::server::router(test_state());
        let response = app
            .oneshot(Request::get("/player/3?t=1").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::SEE_OTHER);
        assert_eq!(response.headers()[header::LOCATION], "/login?next=%2Fplayer%2F3%3Ft%3D1");
    }

    #[test]
    fn bearer_and_cookie_both_authenticate() {
        let token = expected_token("test-password");
        let mut headers = HeaderMap::new();
        headers.insert(header::AUTHORIZATION, format!("bearer {token}").parse().unwrap());
        assert!(is_authenticated(&headers, &token));

        let mut headers = HeaderMap::new();
        headers.insert(header::COOKIE, format!("a=b; {COOKIE_NAME}={token}").parse().unwrap());
        assert!(is_authenticated(&headers, &token));

        let mut headers = HeaderMap::new();
        headers.insert(header::COOKIE, format!("{COOKIE_NAME}=").parse().unwrap());
        assert!(!is_authenticated(&headers, &token));
    }
}
