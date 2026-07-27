use std::env;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use rand::{distr::Alphanumeric, Rng};
use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const CREATE_NO_WINDOW: u32 = 0x0800_0000;

enum BackendChild {
    Development(Child),
    Packaged(CommandChild),
}

impl BackendChild {
    fn force_stop(self) {
        match self {
            Self::Development(mut child) => {
                #[cfg(windows)]
                let _ = terminate_process_tree(child.id());
                #[cfg(not(windows))]
                let _ = child.kill();
                let _ = child.wait();
            }
            Self::Packaged(child) => {
                #[cfg(windows)]
                {
                    let pid = child.pid();
                    // PyInstaller one-file executables use a bootloader plus a Python
                    // child. Killing only the tracked bootloader leaves billable model
                    // work running, so Windows must terminate the full descendant tree.
                    if terminate_process_tree(pid).is_err() {
                        let _ = child.kill();
                    }
                }
                #[cfg(not(windows))]
                let _ = child.kill();
            }
        }
    }
}

#[cfg(windows)]
fn terminate_process_tree(pid: u32) -> Result<(), String> {
    let mut command = Command::new("taskkill.exe");
    command.args(["/PID", &pid.to_string(), "/T", "/F"]);
    hide_child_window(&mut command);
    let status = command
        .status()
        .map_err(|error| format!("failed to start taskkill for process {pid}: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!(
            "taskkill failed for process tree {pid} with status {status}"
        ))
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeCoordinates {
    product_api_origin: String,
    bearer_token: String,
    mode: String,
    logs_dir: String,
    ready: bool,
    error: Option<String>,
}

struct RuntimeProcess {
    child: Option<BackendChild>,
    coordinates: RuntimeCoordinates,
}

struct DesktopRuntime(Mutex<RuntimeProcess>);

fn project_root() -> Option<PathBuf> {
    if let Ok(value) = env::var("CELLWIKI_ROOT") {
        let configured = PathBuf::from(value);
        if configured.join("pyproject.toml").is_file() {
            return Some(configured);
        }
    }

    let mut candidate = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    for _ in 0..5 {
        if candidate.join("pyproject.toml").is_file() {
            return Some(candidate);
        }
        if !candidate.pop() {
            break;
        }
    }
    None
}

fn python_path(root: &Path) -> PathBuf {
    if cfg!(windows) {
        root.join(".venv").join("Scripts").join("python.exe")
    } else {
        root.join(".venv").join("bin").join("python")
    }
}

fn available_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("failed to allocate loopback port: {error}"))?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("failed to inspect loopback port: {error}"))
}

fn launch_token() -> String {
    // The token only lives for this desktop process and is never written to disk.
    rand::rng()
        .sample_iter(&Alphanumeric)
        .take(48)
        .map(char::from)
        .collect()
}

fn port_is_open(port: u16) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&address, Duration::from_millis(150)).is_ok()
}

fn response_is_healthy(response: &[u8]) -> bool {
    response.starts_with(b"HTTP/1.1 200 ") || response.starts_with(b"HTTP/1.0 200 ")
}

fn health_is_ready(port: u16) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(150)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    if stream
        .write_all(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = [0_u8; 256];
    let Ok(bytes_read) = stream.read(&mut response) else {
        return false;
    };
    response_is_healthy(&response[..bytes_read])
}

fn wait_until_ready(port: u16) -> bool {
    // A Python process can bind its socket before importing LangGraph finishes;
    // only a successful health response is a safe signal for the WebView.
    for _ in 0..1_200 {
        if health_is_ready(port) {
            return true;
        }
        thread::sleep(Duration::from_millis(100));
    }
    false
}

fn hide_child_window(command: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(CREATE_NO_WINDOW);
    }
}

fn start_development(root: &Path, port: u16, token: &str) -> Result<BackendChild, String> {
    let python = python_path(root);
    if !python.is_file() {
        return Err(format!(
            "development Python environment not found at {}",
            python.display()
        ));
    }
    let port_argument = port.to_string();
    let mut command = Command::new(python);
    command
        .current_dir(root)
        .args([
            "-m",
            "uvicorn",
            "cellwiki.api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            port_argument.as_str(),
        ])
        .env("CELLWIKI_DESKTOP_TOKEN", token)
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hide_child_window(&mut command);
    command
        .spawn()
        .map(BackendChild::Development)
        .map_err(|error| format!("failed to start development Product API: {error}"))
}

fn start_packaged(
    app: &AppHandle,
    data_dir: &Path,
    port: u16,
    token: &str,
) -> Result<BackendChild, String> {
    let sidecar = app
        .shell()
        .sidecar("cellwiki-sidecar")
        .map_err(|error| format!("packaged sidecar is unavailable: {error}"))?
        .env("CELLWIKI_PORT", port.to_string())
        .env("CELLWIKI_DESKTOP_TOKEN", token)
        .env("CELLWIKI_DATA_DIR", data_dir.to_string_lossy().to_string())
        .env("CELLWIKI_PACKAGED", "1");
    let (mut events, child) = sidecar
        .spawn()
        .map_err(|error| format!("failed to start packaged sidecar: {error}"))?;
    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        // Drain both streams so a verbose child can never block on a full pipe. The
        // Python sidecar writes redacted details to its own rotating log file.
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stderr(bytes) => {
                    let message = String::from_utf8_lossy(&bytes).to_string();
                    let _ = app_handle.emit("cellwiki://backend-error", message);
                }
                CommandEvent::Terminated(payload) => {
                    let _ =
                        app_handle.emit("cellwiki://backend-terminated", format!("{payload:?}"));
                }
                _ => {}
            }
        }
    });
    Ok(BackendChild::Packaged(child))
}

fn start_runtime(app: &AppHandle) -> RuntimeProcess {
    let port = match available_port() {
        Ok(port) => port,
        Err(error) => return failed_coordinates(error),
    };
    let token = launch_token();
    let data_dir = app
        .path()
        .app_data_dir()
        .unwrap_or_else(|_| PathBuf::from("CellWikiData"))
        .join("CellWikiData");
    let logs_dir = data_dir.join("logs");
    let _ = std::fs::create_dir_all(&logs_dir);
    let mode = if cfg!(debug_assertions) {
        "development"
    } else {
        "packaged"
    };
    let result = if cfg!(debug_assertions) {
        project_root()
            .ok_or_else(|| "CellWiki project root was not found".to_string())
            .and_then(|root| start_development(&root, port, &token))
    } else {
        start_packaged(app, &data_dir, port, &token)
    };
    match result {
        Ok(child) => {
            let ready = wait_until_ready(port);
            if !ready {
                child.force_stop();
                return failed_coordinates_with(
                    format!(
                        "CellWiki backend did not become ready; inspect {}",
                        logs_dir.display()
                    ),
                    mode,
                    logs_dir,
                );
            }
            RuntimeProcess {
                child: Some(child),
                coordinates: RuntimeCoordinates {
                    product_api_origin: format!("http://127.0.0.1:{port}"),
                    bearer_token: token,
                    mode: mode.to_string(),
                    logs_dir: logs_dir.to_string_lossy().to_string(),
                    ready: true,
                    error: None,
                },
            }
        }
        Err(error) => failed_coordinates_with(error, mode, logs_dir),
    }
}

fn failed_coordinates(error: String) -> RuntimeProcess {
    failed_coordinates_with(error, "unknown", PathBuf::from("logs"))
}

fn failed_coordinates_with(error: String, mode: &str, logs_dir: PathBuf) -> RuntimeProcess {
    RuntimeProcess {
        child: None,
        coordinates: RuntimeCoordinates {
            product_api_origin: String::new(),
            bearer_token: String::new(),
            mode: mode.to_string(),
            logs_dir: logs_dir.to_string_lossy().to_string(),
            ready: false,
            error: Some(error),
        },
    }
}

fn request_graceful_shutdown(coordinates: &RuntimeCoordinates) {
    if !coordinates.ready {
        return;
    }
    let Some(port) = coordinates
        .product_api_origin
        .rsplit(':')
        .next()
        .and_then(|value| value.parse::<u16>().ok())
    else {
        return;
    };
    if let Ok(mut stream) = TcpStream::connect_timeout(
        &SocketAddr::from(([127, 0, 0, 1], port)),
        Duration::from_millis(300),
    ) {
        let request = format!(
            "POST /api/system/shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            coordinates.bearer_token
        );
        let _ = stream.write_all(request.as_bytes());
        let _ = stream.flush();
    }
}

fn stop_runtime(runtime: &DesktopRuntime) {
    let Ok(mut process) = runtime.0.lock() else {
        return;
    };
    request_graceful_shutdown(&process.coordinates);
    // Give uvicorn and AgentRuntimeManager a bounded opportunity to cancel active
    // model requests. The process-tree termination below remains the hard fallback.
    if let Some(port) = process
        .coordinates
        .product_api_origin
        .rsplit(':')
        .next()
        .and_then(|value| value.parse::<u16>().ok())
    {
        for _ in 0..30 {
            if !port_is_open(port) {
                thread::sleep(Duration::from_millis(300));
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
    }
    if let Some(child) = process.child.take() {
        child.force_stop();
    }
    process.coordinates.ready = false;
}

#[tauri::command]
fn runtime_config(runtime: State<'_, DesktopRuntime>) -> RuntimeCoordinates {
    runtime
        .0
        .lock()
        .map(|process| process.coordinates.clone())
        .unwrap_or_else(|_| RuntimeCoordinates {
            product_api_origin: String::new(),
            bearer_token: String::new(),
            mode: "unknown".to_string(),
            logs_dir: "logs".to_string(),
            ready: false,
            error: Some("desktop runtime lock is poisoned".to_string()),
        })
}

#[tauri::command]
fn restart_backend(
    app: AppHandle,
    runtime: State<'_, DesktopRuntime>,
) -> Result<RuntimeCoordinates, String> {
    stop_runtime(&runtime);
    let replacement = start_runtime(&app);
    let coordinates = replacement.coordinates.clone();
    let mut process = runtime
        .0
        .lock()
        .map_err(|_| "desktop runtime lock is poisoned".to_string())?;
    *process = replacement;
    Ok(coordinates)
}

#[tauri::command]
fn open_logs(runtime: State<'_, DesktopRuntime>) -> Result<(), String> {
    let logs_dir = runtime
        .0
        .lock()
        .map_err(|_| "desktop runtime lock is poisoned".to_string())?
        .coordinates
        .logs_dir
        .clone();
    #[cfg(windows)]
    {
        Command::new("explorer")
            .arg(logs_dir)
            .spawn()
            .map_err(|error| format!("failed to open logs directory: {error}"))?;
    }
    #[cfg(not(windows))]
    {
        let _ = logs_dir;
        return Err("open logs is currently implemented for Windows desktop builds".to_string());
    }
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            runtime_config,
            restart_backend,
            open_logs
        ])
        .setup(|app| {
            app.manage(DesktopRuntime(Mutex::new(start_runtime(app.handle()))));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Agentic CellWiki")
        .run(|app, event| {
            handle_run_event(app, &event);
        })
}

pub fn handle_run_event<R: tauri::Runtime>(app: &tauri::AppHandle<R>, event: &RunEvent) {
    if matches!(event, RunEvent::Exit) {
        stop_runtime(&app.state::<DesktopRuntime>());
    }
}

#[cfg(all(test, target_os = "windows"))]
mod tests {
    use super::{response_is_healthy, terminate_process_tree};
    use std::fs;
    use std::process::Command;
    use std::thread;
    use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

    fn pid_exists(pid: u32) -> bool {
        let filter = format!("PID eq {pid}");
        Command::new("tasklist")
            .args(["/FI", &filter, "/NH"])
            .output()
            .map(|output| String::from_utf8_lossy(&output.stdout).contains(&pid.to_string()))
            .unwrap_or(false)
    }

    #[test]
    fn health_readiness_requires_a_success_response() {
        assert!(response_is_healthy(
            b"HTTP/1.1 200 OK\r\n\r\n{\"status\":\"ok\"}"
        ));
        assert!(!response_is_healthy(
            b"HTTP/1.1 503 Service Unavailable\r\n\r\n"
        ));
        assert!(!response_is_healthy(b"not an HTTP response"));
    }

    #[test]
    fn packaged_fallback_terminates_the_entire_child_tree() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock")
            .as_nanos();
        let pid_file = std::env::temp_dir().join(format!("cellwiki-child-{stamp}.pid"));
        let script = format!(
            "$child = Start-Process -FilePath 'ping.exe' -ArgumentList '-t','127.0.0.1' -WindowStyle Hidden -PassThru; Set-Content -LiteralPath '{}' -Value $child.Id; Wait-Process -Id $child.Id",
            pid_file.display()
        );
        let mut parent = Command::new("powershell.exe")
            .args(["-NoProfile", "-NonInteractive", "-Command", &script])
            .spawn()
            .expect("spawn process-tree fixture");
        let deadline = Instant::now() + Duration::from_secs(3);
        while !pid_file.exists() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(25));
        }
        let child_pid: u32 = fs::read_to_string(&pid_file)
            .expect("child pid file")
            .trim()
            .parse()
            .expect("numeric child pid");

        terminate_process_tree(parent.id()).expect("terminate fixture process tree");
        let _ = parent.wait();
        thread::sleep(Duration::from_millis(150));

        assert!(!pid_exists(parent.id()));
        assert!(!pid_exists(child_pid));
        let _ = fs::remove_file(pid_file);
    }
}
