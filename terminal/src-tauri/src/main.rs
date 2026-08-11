use std::{
    env, fs,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

use tauri::{WebviewUrl, WebviewWindowBuilder};
use uuid::Uuid;

type BoxError = Box<dyn std::error::Error>;

fn required_env(key: &str) -> Result<String, BoxError> {
    env::var(key).map_err(|_| {
        std::io::Error::other(format!(
            "{key} is not set; launch with `compute-bazaar terminal`"
        ))
        .into()
    })
}

fn terminal_port() -> Result<u16, BoxError> {
    let value = required_env("COMPUTE_BAZAAR_TERMINAL_PORT")?;
    value.parse().map_err(|error| {
        std::io::Error::other(format!("invalid terminal port {value}: {error}")).into()
    })
}

fn start_backend(port: u16, native_token: &str) -> Result<Child, BoxError> {
    let python = required_env("COMPUTE_BAZAAR_PYTHON")?;
    let lake_root = required_env("COMPUTE_BAZAAR_LAKE_ROOT")?;
    let project_root = required_env("COMPUTE_BAZAAR_PROJECT_ROOT")?;
    let evaluation_root = required_env("COMPUTE_BAZAAR_EVALUATION_ROOT")?;
    let initial_limit = required_env("COMPUTE_BAZAAR_TERMINAL_INITIAL_LIMIT")?;
    let port = port.to_string();
    let mut command = Command::new(python);
    command
        .current_dir(project_root)
        .args([
            "-m",
            "the_compute_bazaar.cli",
            "--lake-root",
            &lake_root,
            "terminal",
            "--foreground",
            "--no-open",
            "--port",
            &port,
            "--evaluation-root",
            &evaluation_root,
            "--initial-limit",
            &initial_limit,
        ])
        .env("COMPUTE_BAZAAR_TERMINAL_NATIVE_TOKEN", native_token)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    for (environment, option) in [
        ("COMPUTE_BAZAAR_TERMINAL_VIEW", "--view"),
        (
            "COMPUTE_BAZAAR_TERMINAL_INITIAL_QUERY",
            "--initial-query",
        ),
        ("COMPUTE_BAZAAR_TERMINAL_INITIAL_SQL", "--initial-sql"),
        (
            "COMPUTE_BAZAAR_TERMINAL_INITIAL_PERSPECTIVE",
            "--initial-perspective",
        ),
    ] {
        if let Ok(value) = env::var(environment) {
            command.args([option, &value]);
        }
    }

    command.spawn().map_err(Into::into)
}

fn backend_healthy(port: u16) -> bool {
    let address: SocketAddr = match format!("127.0.0.1:{port}").parse() {
        Ok(address) => address,
        Err(_) => return false,
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(200))
    else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(200)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(200)));
    if stream
        .write_all(b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = String::new();
    stream.read_to_string(&mut response).is_ok()
        && response.contains("200 OK")
        && response.contains("compute-bazaar.terminal.health")
}

fn wait_for_backend(child: &mut Child, port: u16) -> Result<(), BoxError> {
    let deadline = Instant::now() + Duration::from_secs(30);
    while Instant::now() < deadline {
        if let Some(status) = child.try_wait()? {
            return Err(std::io::Error::other(format!(
                "terminal backend exited with {status}"
            ))
            .into());
        }
        if backend_healthy(port) {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(100));
    }
    Err(std::io::Error::other("terminal backend did not become ready").into())
}

fn publish_ready(url: &str) -> Result<(), BoxError> {
    let path = PathBuf::from(required_env("COMPUTE_BAZAAR_TERMINAL_READY_FILE")?);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let temporary = path.with_extension("tmp");
    let payload = serde_json::json!({"pid": std::process::id(), "url": url});
    fs::write(&temporary, serde_json::to_vec(&payload)?)?;
    fs::rename(temporary, path)?;
    Ok(())
}

fn stop_backend(backend: &Arc<Mutex<Option<Child>>>) {
    if let Ok(mut guard) = backend.lock() {
        if let Some(child) = guard.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
        *guard = None;
    }
}

fn main() {
    let backend = Arc::new(Mutex::new(None));
    let setup_backend = Arc::clone(&backend);
    let app = tauri::Builder::default()
        .setup(move |app| {
            let port = terminal_port()?;
            let base_url = format!("http://127.0.0.1:{port}");
            let has_initial_state = [
                "COMPUTE_BAZAAR_TERMINAL_VIEW",
                "COMPUTE_BAZAAR_TERMINAL_INITIAL_QUERY",
                "COMPUTE_BAZAAR_TERMINAL_INITIAL_SQL",
                "COMPUTE_BAZAAR_TERMINAL_INITIAL_PERSPECTIVE",
            ]
            .iter()
            .any(|key| env::var_os(key).is_some());
            let launch = Uuid::new_v4().simple().to_string();
            let session = Uuid::new_v4().simple().to_string();
            let window_url = if has_initial_state {
                format!("{base_url}/data?launch={launch}#session={session}")
            } else {
                format!("{base_url}/?launch={launch}#session={session}")
            };
            let mut child = start_backend(port, &session)?;
            if let Err(error) = wait_for_backend(&mut child, port) {
                let _ = child.kill();
                return Err(error);
            }
            *setup_backend.lock().map_err(|_| {
                std::io::Error::other("cannot retain terminal backend process")
            })? = Some(child);
            publish_ready(&base_url)?;
            let (window_width, window_height) = app
                .primary_monitor()?
                .map(|monitor| {
                    let scale = monitor.scale_factor();
                    let work_area = monitor.work_area();
                    (
                        (f64::from(work_area.size.width) / scale * 0.8).max(800.0),
                        (f64::from(work_area.size.height) / scale * 0.8).max(560.0),
                    )
                })
                .unwrap_or((1152.0, 720.0));
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(window_url.parse()?))
                .title("Compute Bazaar Terminal")
                .inner_size(window_width, window_height)
                .min_inner_size(800.0, 560.0)
                .center()
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Compute Bazaar Terminal");

    app.run(|_, _| {});
    stop_backend(&backend);
}
